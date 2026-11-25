# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""What was sent from a folder, and what the site then held.

It is a cache: without it, documents are found again by their reference.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import CliError

FOLDER = ".aipress24"


@dataclass(frozen=True)
class Entry:
    """One document: digests by field, of what was sent and of what resulted."""

    id: int | None = None
    sent: Mapping[str, str] = field(default_factory=dict)
    site: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_pending(self) -> bool:
        """Was the last sending interrupted?"""
        return not self.sent


class State:
    """The entries of a folder, for one site, by reference."""

    def __init__(self, home: Path, site: str, kind: str = "press-release") -> None:
        self._path = home / FOLDER / f"{kind}s.json"
        self._site = site
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._all: dict[str, dict[str, Any]] = {}
            return
        try:
            self._all = json.loads(text)
            for entry in self._all.get(site, {}).values():
                Entry(**entry)
        except (AttributeError, TypeError, ValueError) as error:
            raise CliError(f"{self._path} is damaged, remove it: {error}") from error

    def get(self, reference: str) -> Entry | None:
        entry = self._all.get(self._site, {}).get(reference)
        return Entry(**entry) if entry else None

    def save(self, reference: str, entry: Entry) -> None:
        self._all.setdefault(self._site, {})[reference] = asdict(entry)
        self._path.parent.mkdir(exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._all, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)


def digests(values: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        for key, value in values.items()
    }


def changed(values: Mapping[str, Any], before: Mapping[str, str]) -> tuple[str, ...]:
    """The fields of ``values`` that are not as before."""
    return tuple(
        key for key, digest in digests(values).items() if before.get(key) != digest
    )
