# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The API token of the user."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .errors import CliError


def find_token() -> str:
    """Return the configured token, or an empty string when there is none."""
    token = os.environ.get("AIPRESS24_TOKEN", "").strip()
    if token:
        return token
    path = token_file()
    if not path.exists():
        return ""
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise CliError(f"{path} is readable by others. Run: chmod 600 {path}")
    return path.read_text(encoding="utf-8").strip()


def token_file() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "aipress24" / "token"
