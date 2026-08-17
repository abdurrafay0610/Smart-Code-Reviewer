"""
BaseAgent — the base class every LLM-backed component subclasses.

Design principle #1 says the model is only for judgement; principle #2 says one
decision type per call. ``BaseAgent`` encodes exactly that: one instance
represents ONE bounded DeepSeek task. Nothing subclasses the OpenAI SDK or calls
it directly — the three review agents (``review_agents.py``) and, later, each
rung of the map "climb" (§7.2) subclass ``BaseAgent``, so every model call
funnels through ``deepseek_client.query_deepseek`` with consistent config,
logging, and JSON handling.

A subclass provides three things and calls ``run(payload)``:

    system_prompt(self)              -> the role + rules (WHAT to judge, how)
    build_user_input(self, payload)  -> the evidence for THIS call (WHAT to judge)
    parse_payload(self, obj, resp)   -> turn the parsed JSON into a typed result

``InputT`` and ``ResultT`` are generic, so each subclass gets a precisely typed
``run``: e.g. ``ReviewAgent`` is ``BaseAgent[ReviewInput, AgentResult]``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from .deepseek_client import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    DeepSeekIncompleteResponseError,   # NEW
    DeepSeekModel,
    DeepSeekResponse,
    ReasoningEffort,
    StepLogger,
    query_deepseek,
)

InputT = TypeVar("InputT")
ResultT = TypeVar("ResultT")


class AgentResponseError(RuntimeError):
    """
    Raised when a model response can't be parsed into the expected shape.

    This is distinct from ``DeepSeekIncompleteResponseError`` (the call itself
    failing): here the call succeeded and returned text, but the text wasn't the
    valid JSON the agent's schema requires. The raw content is attached for
    debugging.
    """

    def __init__(self, message: str, *, raw_content: str | None = None) -> None:
        super().__init__(message)
        self.raw_content = raw_content


class BaseAgent(ABC, Generic[InputT, ResultT]):
    """One bounded DeepSeek task. Subclass this; never call the SDK directly."""

    #: Short identifier used in log context (overridden per subclass).
    name: str = "agent"

    def __init__(
        self,
        *,
        logger: StepLogger | None = None,
        model: DeepSeekModel = DEFAULT_MODEL,
        thinking: bool = True,
        reasoning_effort: ReasoningEffort = "high",
        max_tokens: int | None = 8192,
        # When set (and max_tokens is a concrete int), a truncated call
        # (finish_reason="length") is retried with the budget doubled, up to
        # this ceiling. None disables escalation.
        max_token_ceiling: int | None = None,  # NEW
        # JSON is the contract between the model and ``parse``; default it on and
        # request the provider's JSON mode to match.
        json_output: bool = True,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = 2,
        log_content: bool = True,
    ) -> None:
        self.logger = logger
        self.model = model
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.max_token_ceiling = max_token_ceiling  # NEW
        self.json_output = json_output
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.log_content = log_content

    # ---- subclass contract -------------------------------------------------
    @abstractmethod
    def system_prompt(self) -> str:
        """The system message: the agent's role and grounding rules."""

    @abstractmethod
    def build_user_input(self, payload: InputT) -> str:
        """Render the per-call evidence (from ``payload``) into a user message."""

    def parse(self, response: DeepSeekResponse) -> ResultT:
        """
        Turn a raw response into the typed result.

        Default behaviour: parse the content as JSON (tolerating a stray code
        fence) and hand the object to ``parse_payload``. Override ``parse`` for
        non-JSON tasks, or ``parse_payload`` for the common JSON case.
        """
        obj = self._loads(response.content)
        return self.parse_payload(obj, response)

    def parse_payload(self, obj: Any, response: DeepSeekResponse) -> ResultT:
        """Map already-parsed JSON to ``ResultT``. Override for JSON tasks."""
        raise NotImplementedError

    # ---- execution ---------------------------------------------------------
    def run(self, payload: InputT) -> ResultT:
        """Build the messages, call DeepSeek once, and parse the result.

        If the call fails because the model ran out of output budget
        (``finish_reason="length"``) and a ``max_token_ceiling`` is set, the
        budget is doubled and the call retried, up to the ceiling. This is a
        safety net for the thinking-mode synthesis rungs, where reasoning can
        eat a fixed budget — not a substitute for a sensibly sized start.
        """
        user_input = self.build_user_input(payload)
        system_prompt = self.system_prompt()
        budget = self.max_tokens
        while True:
            try:
                response = query_deepseek(
                    self.logger,
                    user_input=user_input,
                    system_prompt=system_prompt,
                    model=self.model,
                    thinking=self.thinking,
                    reasoning_effort=self.reasoning_effort,
                    max_tokens=budget,
                    response_format={"type": "json_object"} if self.json_output else None,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout_seconds=self.timeout_seconds,
                    max_retries=self.max_retries,
                    log_content=self.log_content,
                    log_context={"agent": self.name},
                )
                return self.parse(response)
            except DeepSeekIncompleteResponseError as exc:
                # Only a hard output-budget truncation is worth retrying with a
                # bigger budget; content filtering / other incomplete reasons
                # won't be fixed by more tokens.
                if exc.diagnostics.get("finish_reason") != "length":
                    raise
                next_budget = self._escalated_budget(budget)
                if next_budget is None:
                    raise
                budget = next_budget

    def _escalated_budget(self, current: int | None) -> int | None:
        """Next (doubled) budget, or None if escalation is done/inapplicable.

        Needs a concrete current budget AND a ceiling, and stops once the
        ceiling is reached. ``current`` strictly increases toward a finite
        ceiling, so the retry loop always terminates.
        """
        ceiling = self.max_token_ceiling
        if ceiling is None or current is None or current >= ceiling:
            return None
        return min(current * 2, ceiling)

    # ---- helpers -----------------------------------------------------------
    @staticmethod
    def _loads(content: str) -> Any:
        """
        Parse JSON, tolerating a leading ```json fence some models emit even in
        JSON mode. Raises ``AgentResponseError`` (with the raw content) on
        invalid JSON so callers get a clear, debuggable failure.
        """
        text = content.strip()

        if text.startswith("```"):
            # Drop the opening fence line (``` or ```json) ...
            text = text.split("\n", 1)[1] if "\n" in text else ""
            # ... and the closing fence, if present.
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AgentResponseError(
                f"Model did not return valid JSON: {exc}",
                raw_content=content,
            ) from exc
