# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""``aipress24 post``."""

from __future__ import annotations

from cyclopts import App

from .context import Ctx
from .errors import UsageError
from .press_release import Limit, Only, Sources
from .sources import select

KIND = "post"
NOUN = "post(s)"

app = App(name=KIND, help="Your messages on the wall.")


@app.command
def check(*sources: Sources, only: Only = None, limit: Limit = None, ctx: Ctx) -> None:
    """Report every problem of every post, sending nothing about them."""
    if not sources:
        raise UsageError("Give at least one catalog.")
    selection = select(sources, KIND, only or (), limit)
    if selection.left_out:
        counts = ", ".join(f"{n} {name}" for name, n in selection.left_out.items())
        ctx.say(f"Left out: {counts}.")
    for document in selection.documents:
        ctx.result(
            "invalid" if document.problems else "ready",
            document.title,
            str(document.source),
            ok=not document.problems,
            problems=document.problems,
            warnings=document.warnings,
            source=str(document.source),
            reference=document.reference,
        )
    ctx.summary(NOUN)
