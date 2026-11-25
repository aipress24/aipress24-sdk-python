# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The ``aipress24`` command, which needs the ``cli`` extra."""

from __future__ import annotations

try:
    from .app import main
except ModuleNotFoundError as error:
    msg = f"{error}. Install the command with: uv tool install 'aipress24-client[cli]'"
    raise SystemExit(msg) from error

__all__ = ["main"]
