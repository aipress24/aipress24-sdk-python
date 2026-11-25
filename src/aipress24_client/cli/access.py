# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The API token of the user, for each site."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .errors import CliError


def find_token(site: str) -> str:
    """Return the configured token, or an empty string when there is none."""
    return os.environ.get("AIPRESS24_TOKEN", "").strip() or _read().get(site, "")


def store_token(site: str, token: str) -> Path:
    tokens = {**_read(), site: token}
    return _write(tokens)


def forget_token(site: str) -> bool:
    tokens = _read()
    if tokens.pop(site, None) is None:
        return False
    _write(tokens)
    return True


def _path() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "aipress24" / "tokens.json"


def _read() -> dict[str, str]:
    path = _path()
    if not path.exists():
        return {}
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise CliError(f"{path} is readable by others. Run: chmod 600 {path}")
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (TypeError, ValueError) as error:
        raise CliError(f"{path} is damaged: {error}") from error


def _write(tokens: dict[str, str]) -> Path:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(temporary, flags, 0o600), "w", encoding="utf-8") as file:
        json.dump(tokens, file, indent=1)
    os.replace(temporary, path)
    return path
