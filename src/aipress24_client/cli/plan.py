# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Decide what to do with each document, from what is known of both sides."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .document import REQUIRED_TO_PUBLISH, Document
from .state import Entry, changed

PUBLIC = "public"
IMAGES = "images"


class Action(Enum):
    """What sending a document amounts to."""

    CREATE = "new"
    UPDATE = "changed"
    NOTHING = "unchanged"
    KEEP = "kept"
    CONFLICT = "conflict"
    DELETED = "deleted"


@dataclass(frozen=True)
class Remote:
    """A release on the site, with its carousel."""

    item: Mapping[str, Any]
    images: Sequence[Any]

    @property
    def id(self) -> int:
        return self.item["id"]

    @property
    def is_public(self) -> bool:
        return self.item["status"] == PUBLIC

    def values(self, document: Document) -> dict[str, Any]:
        """What the site holds of what the document says."""
        values = {key: self.item.get(key) for key in document.fields}
        return {**values, IMAGES: list(self.images)}


@dataclass(frozen=True)
class Plan:
    """A document, and what to do with it."""

    document: Document
    action: Action
    entry: Entry | None = None
    remote: Remote | None = None
    changed_here: tuple[str, ...] = ()
    changed_there: tuple[str, ...] = ()

    @property
    def is_public(self) -> bool:
        return self.remote is not None and self.remote.is_public

    def publish_problems(self) -> list[str]:
        """What prevents publishing, counting what the site already has."""
        there = self.remote.item if self.remote else {}
        fields = {**there, **self.document.fields}
        if self.action is Action.KEEP:
            fields = dict(there)
        missing = [
            key
            for key, field in REQUIRED_TO_PUBLISH.items()
            if not (fields.get(field) or "").strip()
        ]
        problems = [f"missing to publish: {', '.join(missing)}"] if missing else []
        embargo = fields.get("embargoed_until")
        if embargo and datetime.fromisoformat(embargo) > datetime.now(UTC):
            problems.append(f"under embargo until {embargo}")
        return problems


def local_values(document: Document) -> dict[str, Any]:
    images = [list(image.key) for image in document.images]
    return {**document.fields, IMAGES: images}


def make_plan(
    document: Document,
    entry: Entry | None,
    remote: Remote | None,
    *,
    overwrite: bool = False,
    recreate: bool = False,
) -> Plan:
    here: tuple[str, ...] = ()
    there: tuple[str, ...] = ()
    if entry and not entry.is_pending:
        here = changed(local_values(document), entry.sent)
        if remote:
            # A field the document did not have when it was sent has no digest.
            known = {
                key: value
                for key, value in remote.values(document).items()
                if key in entry.site
            }
            there = changed(known, entry.site)
    action = _decide(
        entry, remote, bool(here), bool(there), overwrite=overwrite, recreate=recreate
    )
    return Plan(document, action, entry, remote, here, there)


def _decide(
    entry: Entry | None,
    remote: Remote | None,
    here: bool,
    there: bool,
    *,
    overwrite: bool,
    recreate: bool,
) -> Action:
    if remote is None:
        is_new = entry is None or entry.id is None
        return Action.CREATE if is_new or recreate else Action.DELETED
    if entry is None:
        return Action.UPDATE if overwrite else Action.CONFLICT
    if entry.is_pending:
        return Action.UPDATE
    if here and there:
        return Action.UPDATE if overwrite else Action.CONFLICT
    if here:
        return Action.UPDATE
    return Action.KEEP if there else Action.NOTHING
