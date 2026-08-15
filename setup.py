#!/usr/bin/env python3
"""Download the Ruff binary into ./bin.

Ruff is the one genuine compiled binary in the Python adapter; lizard and radon are
pure-Python packages (requirements.txt) used through their APIs. This script fetches a
standalone Ruff build so its version is decoupled from the Python environment. The tool
layer looks for ./bin/ruff first, then falls back to any `ruff` on PATH.

This is intentionally NOT a setuptools script and does not install requirements.txt - it
only places binaries. Run it once, after installing requirements:

    pip install -r requirements.txt
    python setup.py

Version resolution: RUFF_VERSION env var, else the latest GitHub release, else the pinned
DEFAULT_RUFF_VERSION. The actual download uses github.com/releases/download directly (a
stable naming convention), so it works even when the GitHub API is rate-limited or
unreachable. Stdlib only, so it runs before anything else is installed.
"""

from __future__ import annotations

import io
import json
import os
import platform
import stat
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BIN_DIR = BASE_DIR / "bin"  # must match backend/config.py BIN_DIR
DEFAULT_RUFF_VERSION = "0.16.3"  # fallback when the API can't be reached
_UA = {"User-Agent": "smart-code-reviewer-setup"}


def _ruff_target() -> tuple[str, str]:
    """Return (release-target-triple, archive-extension) for this machine."""
    system = platform.system()
    machine = platform.machine().lower()
    is_arm = machine in {"arm64", "aarch64"}
    is_x86 = machine in {"x86_64", "amd64"}
    if system == "Linux" and is_x86:
        return "x86_64-unknown-linux-gnu", ".tar.gz"
    if system == "Linux" and is_arm:
        return "aarch64-unknown-linux-gnu", ".tar.gz"
    if system == "Darwin" and is_x86:
        return "x86_64-apple-darwin", ".tar.gz"
    if system == "Darwin" and is_arm:
        return "aarch64-apple-darwin", ".tar.gz"
    if system == "Windows" and is_x86:
        return "x86_64-pc-windows-msvc", ".zip"
    raise SystemExit(
        f"Unsupported platform: {system} / {machine}. "
        "Install ruff manually with `pip install ruff`."
    )


def _resolve_version() -> str:
    """RUFF_VERSION env var, else latest GitHub release, else the pinned default."""
    pinned = os.environ.get("RUFF_VERSION")
    if pinned:
        return pinned
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/astral-sh/ruff/releases/latest", headers=_UA
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            tag = json.load(resp).get("tag_name")
            if tag:
                return tag
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(
            f"  (could not query latest version: {exc};\n"
            f"   falling back to pinned {DEFAULT_RUFF_VERSION})"
        )
    return DEFAULT_RUFF_VERSION


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def _extract_ruff(archive: bytes, ext: str, dest_dir: Path) -> Path:
    """Extract the ruff executable from the archive into dest_dir; return its path."""
    binary_name = "ruff.exe" if os.name == "nt" else "ruff"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if ext == ".zip":
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                zf.extractall(tmp_path)
        else:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
                tf.extractall(tmp_path)
        found = next((p for p in tmp_path.rglob(binary_name) if p.is_file()), None)
        if found is None:
            raise SystemExit("Downloaded archive did not contain a ruff binary.")
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / binary_name
        target.write_bytes(found.read_bytes())
        target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return target


def main() -> None:
    target, ext = _ruff_target()
    version = _resolve_version()
    url = f"https://github.com/astral-sh/ruff/releases/download/{version}/ruff-{target}{ext}"
    print(f"Platform target : {target}")
    print(f"Ruff version    : {version}")
    print(f"Downloading     : {url}")
    try:
        archive = _download(url)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"Download failed ({exc.code}). Check the version/URL, or "
            "install ruff with `pip install ruff`."
        ) from exc
    print(f"                  {len(archive):,} bytes")
    binary = _extract_ruff(archive, ext, BIN_DIR)
    print(f"Installed ruff  : {binary}")


if __name__ == "__main__":
    main()
