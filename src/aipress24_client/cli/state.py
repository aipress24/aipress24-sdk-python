# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The release a folder was pushed to, remembered next to its files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import CliError

STATE_FILE = ".aipress24.json"


@dataclass(frozen=True)
class State:
    """The release a folder was pushed to, and its date after the push."""

    base_url: str
    id: int
    modified_at: str | None = None


def load_state(folder: Path, base_url: str) -> State | None:
    path = folder / STATE_FILE
    if not path.exists():
        return None
    try:
        state = State(**json.loads(path.read_text(encoding="utf-8")))
    except (TypeError, ValueError) as error:
        raise CliError(f"{path} is damaged: {error}") from error
    if state.base_url != base_url:
        raise CliError(f"{folder} was pushed to {state.base_url}, not to {base_url}.")
    return state


def save_state(folder: Path, state: State) -> None:
    path = folder / STATE_FILE
    path.write_text(json.dumps(vars(state), indent=2) + "\n", encoding="utf-8")
