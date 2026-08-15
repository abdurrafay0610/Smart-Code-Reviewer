"""
DeepSeek client — the single, low-level choke point for every model call.

Nothing else in this codebase talks to DeepSeek directly. The agent base class
(``base.BaseAgent``) wraps this function, and the review agents and (later) the
map engine all go through that base — so all provider access funnels here with
consistent validation, diagnostics, and incomplete-response handling.

This started life as a test-suite helper. Three things were generalised so it
fits an application, not just a test harness (all behaviour-preserving):

  1. The ``logger`` is now optional. Pass any object exposing ``start_step`` /
     ``step_passed`` / ``step_failed`` (e.g. a rich test logger); omit it and
     logging is a no-op.
  2. The OpenAI SDK is imported lazily inside the call, so the deterministic
     shell (clone / branches / diff) still imports and runs even when the LLM
     dependencies aren't installed.
  3. ``python-dotenv`` is optional — if present, a local ``.env`` is loaded so
     ``DEEPSEEK_API_KEY`` is picked up automatically.

Everything else — argument validation, token-usage diagnostics, and the
"incomplete response" detection — is unchanged.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

# Optional: load variables from a local .env into the environment if python-dotenv
# is installed. It's not required for the deterministic parts of the app.
try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv not installed — fine.
    pass


# ---------------------------------------------------------------------------- #
# Logging seam
# ---------------------------------------------------------------------------- #
@runtime_checkable
class StepLogger(Protocol):
    """
    Minimal structured-logging interface this module uses.

    A full test logger satisfies this by duck typing; so does any small adapter
    you write. When no logger is supplied, ``_NULL_LOGGER`` is used and all
    logging calls become no-ops.
    """

    def start_step(self, message: str, **kwargs: Any) -> Any: ...

    def step_passed(self, message: str, **kwargs: Any) -> Any: ...

    def step_failed(self, message: str, **kwargs: Any) -> Any: ...


class _NullStepLogger:
    """A logger that swallows everything. Used when no logger is provided."""

    def start_step(self, *args: Any, **kwargs: Any) -> None:
        return None

    def step_passed(self, *args: Any, **kwargs: Any) -> None:
        return None

    def step_failed(self, *args: Any, **kwargs: Any) -> None:
        return None


_NULL_LOGGER = _NullStepLogger()


# Restrict model names at type-checking time and validate them again at runtime.
# Runtime validation is still necessary because callers can bypass type hints.
DeepSeekModel = Literal[
    "deepseek-v4-flash",
    "deepseek-v4-pro",
]

# These are the only conversation roles this helper currently supports.
#
# Tool messages are intentionally excluded because this helper is intended for
# generic text evaluation and subjective judgments, not tool-calling workflows.
DeepSeekRole = Literal[
    "system",
    "user",
    "assistant",
]

# DeepSeek currently exposes these two effective reasoning-effort levels.
ReasoningEffort = Literal[
    "high",
    "max",
]


# Centralized defaults keep all DeepSeek calls consistent across the codebase.
# Individual callers can still override any of them when required.
DEFAULT_MODEL: DeepSeekModel = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 120.0

# Every log written by this module uses the same component and layer.
_COMPONENT = "DeepSeekClient"
_LOGGER_LAYER = "deepseek"


class DeepSeekIncompleteResponseError(RuntimeError):
    """
    Raised when DeepSeek returns a response but no complete final answer.

    This is different from a network or API error. The request succeeded, but
    the response cannot safely be used. For example:

        - The model exhausted max_tokens.
        - Thinking consumed the complete output-token budget.
        - The final answer was empty.
        - The model stopped because of content filtering.
        - The model stopped because of insufficient system resources.

    The diagnostics are stored on the exception so the common exception handler
    can include finish-reason and token information in the log.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Mapping[str, Any],
    ) -> None:
        super().__init__(message)
        # Copy the mapping so later caller changes cannot alter the diagnostic
        # information associated with this failure.
        self.diagnostics = dict(diagnostics)


class DeepSeekMessage(TypedDict):
    """Normalized message format accepted by this helper."""

    role: DeepSeekRole
    content: str


@dataclass(frozen=True, slots=True)
class DeepSeekResponse:
    """
    Normalized result returned by query_deepseek().

    Using our own dataclass gives the rest of the codebase a stable response
    interface instead of depending directly on classes from the OpenAI SDK.

    Fields:
        content: The final answer produced by DeepSeek.
        model: The actual model reported by DeepSeek.
        finish_reason: Why DeepSeek stopped generating ("stop" on success).
        reasoning_content: DeepSeek's reasoning output when thinking is enabled
            (returned for optional debugging; never written to logs).
        prompt_tokens: Input tokens used.
        completion_tokens: Total generated tokens (reasoning + final answer).
        reasoning_tokens: Completion tokens consumed by reasoning.
        total_tokens: Combined prompt and completion usage.
        raw_response: Complete provider response as a plain dict, for advanced
            callers needing a field not surfaced directly here.
    """

    content: str
    model: str
    finish_reason: str | None
    reasoning_content: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    raw_response: dict[str, Any]


def _normalize_text(
    value: str,
    argument_name: str,
) -> str:
    """
    Validate and trim a required text value.

    Trimming prevents whitespace-only prompts from being sent and makes the
    logged prompt match the exact content submitted to DeepSeek.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{argument_name} must be a non-empty string.")

    return value.strip()


def _normalize_history(
    history: Sequence[Mapping[str, str]] | None,
) -> list[DeepSeekMessage]:
    """
    Validate and copy conversation history.

    Only role and content are retained. This prevents accidentally resending
    provider-specific response fields, reasoning content, token-usage
    information, or mutable dictionaries owned by the caller. The caller's
    original history is never modified.
    """
    normalized_history: list[DeepSeekMessage] = []

    for index, message in enumerate(history or []):
        if not isinstance(message, Mapping):
            raise TypeError(
                f"history[{index}] must be a mapping containing "
                "'role' and 'content'."
            )

        role = message.get("role")
        content = message.get("content")

        if role not in {"system", "user", "assistant"}:
            raise ValueError(
                f"history[{index}]['role'] must be "
                "'system', 'user', or 'assistant'."
            )

        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                f"history[{index}]['content'] must be a non-empty string."
            )

        normalized_history.append(
            {
                "role": role,
                "content": content.strip(),
            }
        )

    return normalized_history


def _extract_reasoning_tokens(
    usage: Any | None,
) -> int | None:
    """
    Extract the reasoning-token count from the API usage object.

    The field may not exist when thinking mode is disabled, the API omits
    detailed completion usage, or the installed SDK does not expose it.
    getattr() keeps missing optional metadata from failing a valid response.
    """
    if usage is None:
        return None

    completion_token_details = getattr(
        usage,
        "completion_tokens_details",
        None,
    )

    if completion_token_details is None:
        return None

    reasoning_tokens = getattr(
        completion_token_details,
        "reasoning_tokens",
        None,
    )

    return reasoning_tokens if isinstance(reasoning_tokens, int) else None


def _estimate_final_answer_tokens(
    completion_tokens: int | None,
    reasoning_tokens: int | None,
) -> int | None:
    """
    Estimate how many generated tokens were used by the final answer.

    DeepSeek includes reasoning tokens within completion-token usage, so:

        estimated final-answer tokens = completion tokens - reasoning tokens

    This is useful for spotting the case where reasoning consumed the whole
    budget and left zero tokens for the answer. max(..., 0) guards against
    inconsistent provider metadata.
    """
    if completion_tokens is None or reasoning_tokens is None:
        return None

    return max(completion_tokens - reasoning_tokens, 0)


def query_deepseek(
    logger: StepLogger | None = None,
    *,
    user_input: str,
    system_prompt: str | None = None,
    history: Sequence[Mapping[str, str]] | None = None,
    model: DeepSeekModel = DEFAULT_MODEL,
    thinking: bool = True,
    reasoning_effort: ReasoningEffort = "high",
    max_tokens: int | None = 8192,
    temperature: float | None = None,
    response_format: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = 2,
    log_content: bool = True,
    log_context: Mapping[str, Any] | None = None,
) -> DeepSeekResponse:
    """
    Send a generic, non-streaming request to DeepSeek.

    Messages are submitted as: system_prompt -> history -> current user_input.
    The supplied history is copied and never modified.

    Args:
        logger: Optional structured logger (see ``StepLogger``). Omit for a
            no-op.
        user_input: Current user message or content being evaluated.
        system_prompt: Optional instruction defining DeepSeek's task/behavior.
        history: Optional previous conversation messages.
        model: "deepseek-v4-flash" or "deepseek-v4-pro".
        thinking: Enable/disable DeepSeek thinking mode. Improves difficult
            judgments but consumes output tokens and increases latency/cost.
        reasoning_effort: "high" or "max"; only sent when thinking is enabled.
        max_tokens: Generated-token budget (reasoning + final answer). None
            lets the provider use its default.
        temperature: 0-2. Only usable when thinking=False (DeepSeek ignores it
            while thinking).
        response_format: e.g. {"type": "json_object"}. When JSON is requested,
            the prompt must also instruct DeepSeek to return JSON.
        api_key: Explicit key; otherwise DEEPSEEK_API_KEY is read.
        base_url: Explicit base URL; otherwise DEEPSEEK_BASE_URL then the
            official endpoint.
        timeout_seconds: Client-side request timeout.
        max_retries: Transport/API retries handled by the OpenAI client.
            Incomplete answers are deliberately not retried automatically.
        log_content: When True, prompts/history/final content are logged. The
            API key and reasoning content are never logged.
        log_context: Optional caller-defined metadata for the logs.

    Returns:
        A normalized DeepSeekResponse.

    Raises:
        ValueError: An argument is invalid or the API key is missing.
        DeepSeekIncompleteResponseError: No usable final answer.
        Exception: Provider/SDK/auth/timeout/rate-limit/network failures are
            logged and re-raised.
    """

    active_logger: StepLogger = logger if logger is not None else _NULL_LOGGER

    # -----------------------------------------------------------------------
    # Argument validation
    # -----------------------------------------------------------------------
    user_input = _normalize_text(user_input, "user_input")

    if system_prompt is not None:
        system_prompt = _normalize_text(system_prompt, "system_prompt")

    if model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
        raise ValueError("model must be 'deepseek-v4-flash' or 'deepseek-v4-pro'.")

    if reasoning_effort not in {"high", "max"}:
        raise ValueError("reasoning_effort must be 'high' or 'max'.")

    if max_tokens is not None:
        # bool is a subclass of int in Python, so reject it explicitly.
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
            raise TypeError("max_tokens must be a positive integer or None.")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than 0.")

    if temperature is not None:
        # DeepSeek ignores temperature in thinking mode. Raising is safer than
        # accepting a config that appears to work but does not affect the model.
        if thinking:
            raise ValueError(
                "temperature cannot be used while thinking mode is enabled."
            )
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise TypeError("temperature must be a number or None.")
        if not 0 <= float(temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2.")

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")

    if not isinstance(max_retries, int) or isinstance(max_retries, bool):
        raise TypeError("max_retries must be an integer greater than or equal to 0.")

    if max_retries < 0:
        raise ValueError("max_retries must be greater than or equal to 0.")

    # -----------------------------------------------------------------------
    # API configuration
    # -----------------------------------------------------------------------
    resolved_api_key = api_key or os.getenv("DEEPSEEK_API_KEY")

    if not resolved_api_key or not resolved_api_key.strip():
        raise ValueError(
            "DeepSeek API key is missing. Set DEEPSEEK_API_KEY or pass api_key."
        )

    # The trailing slash is removed because the SDK appends /chat/completions.
    resolved_base_url = (
        base_url or os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
    ).strip().rstrip("/")

    if not resolved_base_url:
        raise ValueError("base_url must be a non-empty URL.")

    normalized_history = _normalize_history(history)

    # Copy optional mappings once so later caller mutations can't change what
    # was recorded in the logs or sent to the API.
    normalized_response_format = (
        dict(response_format) if response_format is not None else None
    )
    normalized_log_context = dict(log_context) if log_context is not None else None

    # -----------------------------------------------------------------------
    # Message construction
    # -----------------------------------------------------------------------
    messages: list[DeepSeekMessage] = []

    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})

    messages.extend(normalized_history)
    messages.append({"role": "user", "content": user_input})

    # -----------------------------------------------------------------------
    # Request logging
    # -----------------------------------------------------------------------
    request_details: dict[str, Any] = {
        "model": model,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort if thinking else None,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "message_count": len(messages),
        "history_message_count": len(normalized_history),
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "response_format": normalized_response_format,
        "log_context": normalized_log_context,
    }

    if log_content:
        request_details["messages"] = messages

    active_logger.start_step(
        "Querying DeepSeek",
        layer=_LOGGER_LAYER,
        component=_COMPONENT,
        action="query_deepseek",
        details=request_details,
    )

    started_at = time.perf_counter()

    try:
        # -------------------------------------------------------------------
        # Client creation (SDK imported lazily so the deterministic shell does
        # not require the OpenAI package just to import this module).
        # -------------------------------------------------------------------
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "The 'openai' package is required to call DeepSeek. "
                "Install it with `pip install openai`."
            ) from exc

        # DeepSeek exposes an OpenAI-compatible API, so the OpenAI SDK can be
        # pointed at DeepSeek by supplying its API key and base URL.
        client = OpenAI(
            api_key=resolved_api_key.strip(),
            base_url=resolved_base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

        # -------------------------------------------------------------------
        # Request construction
        # -------------------------------------------------------------------
        request_options: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "extra_body": {
                "thinking": {
                    "type": "enabled" if thinking else "disabled",
                },
            },
        }

        if thinking:
            request_options["reasoning_effort"] = reasoning_effort

        if max_tokens is not None:
            request_options["max_tokens"] = max_tokens

        if temperature is not None:
            request_options["temperature"] = float(temperature)

        if normalized_response_format is not None:
            request_options["response_format"] = normalized_response_format

        # Non-streaming: callers need one complete, deterministic response
        # object before evaluating the result.
        response = client.chat.completions.create(**request_options)

        # -------------------------------------------------------------------
        # Basic provider-response validation
        # -------------------------------------------------------------------
        if not response.choices:
            raise RuntimeError("DeepSeek returned no response choices.")

        choice = response.choices[0]

        # content may be null when DeepSeek produced no final answer. Normalize
        # to "" so the incomplete-response checks below run and finish/usage can
        # be logged before failing.
        raw_content = choice.message.content

        if raw_content is None:
            content = ""
        elif isinstance(raw_content, str):
            content = raw_content
        else:
            raise RuntimeError("DeepSeek returned final content in an unsupported format.")

        reasoning_content = getattr(choice.message, "reasoning_content", None)
        if not isinstance(reasoning_content, str):
            reasoning_content = None

        # -------------------------------------------------------------------
        # Usage and finish diagnostics
        # -------------------------------------------------------------------
        usage = response.usage
        reasoning_tokens = _extract_reasoning_tokens(usage)
        finish_reason = choice.finish_reason

        prompt_tokens = usage.prompt_tokens if usage is not None else None
        completion_tokens = usage.completion_tokens if usage is not None else None
        total_tokens = usage.total_tokens if usage is not None else None

        response_diagnostics: dict[str, Any] = {
            "response_id": getattr(response, "id", None),
            "request_id": getattr(response, "_request_id", None),
            "model": response.model,
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "estimated_final_answer_tokens": _estimate_final_answer_tokens(
                completion_tokens,
                reasoning_tokens,
            ),
            "total_tokens": total_tokens,
            "reasoning_character_count": len(reasoning_content or ""),
            "response_character_count": len(content),
        }

        # -------------------------------------------------------------------
        # Incomplete-response detection
        # -------------------------------------------------------------------
        # finish_reason="length" means the model hit its output-token limit.
        if finish_reason == "length":
            raise DeepSeekIncompleteResponseError(
                (
                    "DeepSeek exhausted its output-token budget before "
                    "producing a complete final answer."
                ),
                diagnostics=response_diagnostics,
            )

        # A blank final answer is always unusable (includes the case where
        # reasoning consumed all completion tokens).
        if not content.strip():
            raise DeepSeekIncompleteResponseError(
                "DeepSeek returned an empty final answer.",
                diagnostics=response_diagnostics,
            )

        # This helper does not support tool calls or partial/filtered results,
        # so only a natural "stop" is treated as successful.
        if finish_reason != "stop":
            raise DeepSeekIncompleteResponseError(
                f"DeepSeek did not complete normally. finish_reason={finish_reason!r}.",
                diagnostics=response_diagnostics,
            )

        # -------------------------------------------------------------------
        # Successful response normalization
        # -------------------------------------------------------------------
        result = DeepSeekResponse(
            content=content,
            model=response.model,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            raw_response=response.model_dump(),
        )

        elapsed_seconds = time.perf_counter() - started_at

        success_details: dict[str, Any] = {
            **response_diagnostics,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "has_reasoning_content": result.reasoning_content is not None,
            "log_context": normalized_log_context,
        }

        if log_content:
            success_details["content"] = result.content

        active_logger.step_passed(
            "DeepSeek responded successfully",
            layer=_LOGGER_LAYER,
            component=_COMPONENT,
            action="query_deepseek",
            details=success_details,
        )

        return result

    except Exception as error:
        elapsed_seconds = time.perf_counter() - started_at

        failure_details: dict[str, Any] = {
            "model": model,
            "thinking": thinking,
            "reasoning_effort": reasoning_effort if thinking else None,
            "max_tokens": max_tokens,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "status_code": getattr(error, "status_code", None),
            "request_id": getattr(error, "request_id", None),
            "log_context": normalized_log_context,
        }

        # Incomplete responses carry richer diagnostics from the successful API
        # response; merge them so token exhaustion / abnormal finish reasons are
        # immediately visible in the failure log.
        if isinstance(error, DeepSeekIncompleteResponseError):
            failure_details.update(error.diagnostics)

        active_logger.step_failed(
            "DeepSeek query failed",
            layer=_LOGGER_LAYER,
            component=_COMPONENT,
            action="query_deepseek",
            details=failure_details,
            exception=error,
        )

        # Do not swallow the exception — let the caller handle/fail naturally.
        raise
