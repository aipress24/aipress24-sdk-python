# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""``aipress24 post``.

A post cannot be modified on the site, so there is nothing to compare but whether
it is there, and whether it is the same.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import cache
from pathlib import Path
from typing import Any

from cyclopts import App

from .. import ApiError
from .context import Context, Ctx
from .document import Document
from .errors import CliError, UsageError
from .press_release import (
    DryRun,
    Limit,
    Only,
    Recreate,
    SkipInvalid,
    Sources,
    Targets,
    Yes,
    api_message,
    are_items,
)
from .site import NETWORK_ERRORS, POSTS, Site
from .sources import is_item, select
from .state import Entry, State, digests

KIND = "post"
NOUN = "post(s)"
TOO_MANY_REQUESTS = 429

app = App(name=KIND, help="Your messages on the wall.")


class Status(Enum):
    """A document, compared with the site."""

    NEW = "new"
    SAME = "unchanged"
    DIFFERENT = "different"
    DELETED = "deleted"


@dataclass(frozen=True)
class Found:
    """A document, and the post it is on the site."""

    document: Document
    status: Status
    item: Mapping[str, Any] | None = None


# --- reading ---------------------------------------------------------------


@app.command
def check(*sources: Sources, only: Only = None, limit: Limit = None, ctx: Ctx) -> None:
    """Report every problem of every post, sending nothing about them."""
    for document in _select(ctx, sources, only, limit):
        if document.problems:
            _report_invalid(ctx, document)
        else:
            _report(ctx, "ready", document, None, detail=str(document.source))
    ctx.summary(NOUN)


@app.command
def status(*sources: Sources, only: Only = None, limit: Limit = None, ctx: Ctx) -> None:
    """Compare each message with the site."""
    for document in _select(ctx, sources, only, limit):
        show_status(ctx, document)
    ctx.summary(NOUN)


def show_status(ctx: Context, document: Document) -> None:
    if document.problems:
        _report_invalid(ctx, document)
    else:
        found = _find(ctx.site, document)
        _report(ctx, found.status.value, document, found.item)


@app.command(name="list")
def list_(*, ctx: Ctx) -> None:
    """List your posts."""
    for item in ctx.site.posts:
        text = f"{item['id']}  {item['published_at'][:10]}  {_title(item)}"
        ctx.line(text, _describe(ctx, item))


@app.command
def show(*targets: Targets, ctx: Ctx) -> None:
    """Show posts, as they are on the site."""
    for item in _items(ctx, targets):
        details = _describe(ctx, item)
        ctx.line(
            "\n".join(f"{key}: {value}" for key, value in details.items()), details
        )


# --- writing ---------------------------------------------------------------


@app.command
def publish(
    *sources: Sources,
    only: Only = None,
    limit: Limit = None,
    skip_invalid: SkipInvalid = False,
    recreate: Recreate = False,
    dry_run: DryRun = False,
    yes: Yes = False,
    ctx: Ctx,
) -> None:
    """Have each message on the wall, at its own date."""
    valid = []
    documents = _select(ctx, sources, only, limit)
    for document in documents:
        if document.problems:
            _report_invalid(ctx, document)
        else:
            valid.append(document)
    if len(valid) < len(documents) and not skip_invalid and not dry_run:
        raise CliError(
            f"Nothing was sent: {len(documents) - len(valid)} of {len(documents)} "
            "are invalid. Use --skip-invalid to send the others."
        )
    plans = [_find(ctx.site, document) for document in valid]
    todo = [found for found in plans if _is_to_create(found, recreate=recreate)]
    if todo:
        question = _publication_summary(ctx, todo)
        if dry_run:
            ctx.say(question)
        else:
            ctx.confirm(question, yes=yes)
    for found in plans:
        if dry_run or not _is_to_create(found, recreate=recreate):
            # What is there, but not as here, cannot be brought up to date.
            ok = dry_run or found.status is Status.SAME
            _report(ctx, found.status.value, found.document, found.item, ok=ok)
        else:
            _create(ctx, found.document)
    hints = []
    if ctx.results[Status.DIFFERENT.value]:
        hints.append("A post cannot be modified: delete it, then publish it again.")
    if ctx.results[Status.DELETED.value] and not recreate:
        hints.append("--recreate creates again what was deleted on the site.")
    if ctx.results["failed"]:
        hints.append("Run the same command again to do what is left.")
    ctx.summary(NOUN, *hints)


@app.command
def delete(
    *targets: Targets,
    only: Only = None,
    limit: Limit = None,
    dry_run: DryRun = False,
    yes: Yes = False,
    ctx: Ctx,
) -> None:
    """Delete posts from the site, for good."""
    items = _items(ctx, targets, only, limit)
    if items:
        titles = "\n".join(f"  {_title(item)}" for item in items[:20])
        more = f"\n  and {len(items) - 20} more" if len(items) > 20 else ""
        question = f"Delete {len(items)} {NOUN} on {ctx.site.url}:\n{titles}{more}"
        if dry_run:
            ctx.say(question)
            return
        ctx.confirm(question, yes=yes)
    for item in items:
        try:
            ctx.site.client.delete(POSTS, item["id"])
        except (ApiError, *NETWORK_ERRORS) as error:
            _report_item(ctx, "failed", item, _failure(error), ok=False)
        else:
            _report_item(ctx, "deleted", item)
    ctx.summary(NOUN)


# --- documents -------------------------------------------------------------


def _select(
    ctx: Context,
    sources: Sequence[Path],
    only: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[Document]:
    if not sources:
        raise UsageError("Give at least one catalog.")
    if any(is_item(str(source)) for source in sources):
        raise UsageError("This command takes catalogs, not ids or URLs.")
    selection = select(sources, KIND, only or (), limit)
    if selection.left_out:
        counts = ", ".join(f"{n} {name}" for name, n in selection.left_out.items())
        ctx.say(f"Left out: {counts}.")
    return selection.documents


def _find(site: Site, document: Document) -> Found:
    item = _by_reference(site).get(document.reference)
    if item is None:
        entry = _state(document.home, site.url).get(document.reference)
        return Found(document, Status.DELETED if entry else Status.NEW)
    same = (
        item["text"] == document.fields["content"].strip()
        and _images_of(item) == [list(image.key) for image in document.images]
        and _moment(item["published_at"]) == _moment(document.fields["published_at"])
    )
    return Found(document, Status.SAME if same else Status.DIFFERENT, item)


def _by_reference(site: Site) -> dict[str, dict[str, Any]]:
    return {item["external_ref"]: item for item in site.posts if item["external_ref"]}


@cache
def _state(home: Path, site_url: str) -> State:
    return State(home, site_url, KIND)


def _create(ctx: Context, document: Document) -> None:
    fields = document.fields
    try:
        item = ctx.site.client.create_post(
            fields["content"],
            published_at=fields["published_at"],
            external_ref=fields["external_ref"],
            images=[
                (image.name, image.content, image.caption) for image in document.images
            ],
        )
    except (ApiError, *NETWORK_ERRORS) as error:
        _report(ctx, "failed", document, None, detail=_failure(error), ok=False)
        return
    entry = Entry(item["id"], sent=digests({"content": fields["content"]}))
    _state(document.home, ctx.site.url).save(document.reference, entry)
    _report(ctx, "published", document, item)


def _failure(error: Exception) -> str:
    """What to say of a failure; those that concern every post are raised."""
    if not isinstance(error, ApiError):
        return str(error)
    if error.status == 401:
        raise error
    if error.status == TOO_MANY_REQUESTS:
        raise CliError(
            f"{api_message(error)} Run the same command again tomorrow."
        ) from error
    return api_message(error)


def _is_to_create(found: Found, *, recreate: bool) -> bool:
    return found.status is Status.NEW or (recreate and found.status is Status.DELETED)


def _publication_summary(ctx: Context, todo: Sequence[Found]) -> str:
    dates = sorted(found.document.fields["published_at"][:10] for found in todo)
    name = ctx.site.client.me()["full_name"]
    return (
        f"Publish {len(todo)} {NOUN} on {ctx.site.url}, as {name}:\n"
        f"  dated from {dates[0]} to {dates[-1]}"
    )


def _images_of(item: Mapping[str, Any]) -> list[list[Any]]:
    return [[image["sha256"], image["caption"], ""] for image in item["images"]]


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


# --- reports ---------------------------------------------------------------


def _items(
    ctx: Context,
    targets: Sequence[str],
    only: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    """The items given, or those of the messages of the catalogs given."""
    if not targets:
        raise UsageError("Give at least one catalog, id or URL.")
    if are_items(targets):
        return [ctx.site.find_post(target) for target in targets]
    found = _by_reference(ctx.site)
    items = []
    for document in _select(ctx, [Path(target) for target in targets], only, limit):
        if item := found.get(document.reference):
            items.append(item)
        else:
            _report(ctx, "absent", document, None)
    return items


def _report_invalid(ctx: Context, document: Document) -> None:
    ctx.result(
        "invalid",
        document.title,
        str(document.source),
        ok=False,
        problems=document.problems,
        warnings=document.warnings,
        source=str(document.source),
        reference=document.reference,
    )


def _report(
    ctx: Context,
    result: str,
    document: Document,
    item: Mapping[str, Any] | None,
    *,
    detail: str = "",
    ok: bool = True,
) -> None:
    page = ctx.site.page(item) if item else ""
    ctx.result(
        result,
        document.title,
        detail or page,
        ok=ok,
        warnings=document.warnings,
        source=str(document.source),
        reference=document.reference,
        id=item["id"] if item else None,
        page=page or None,
    )


def _report_item(
    ctx: Context,
    result: str,
    item: Mapping[str, Any],
    detail: str = "",
    *,
    ok: bool = True,
) -> None:
    ctx.result(
        result,
        _title(item),
        detail,
        ok=ok,
        id=item["id"],
        reference=item["external_ref"],
    )


def _title(item: Mapping[str, Any]) -> str:
    return " ".join(item["text"].split()) or "(no text)"


def _describe(ctx: Context, item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "text": item["text"],
        "published_at": item["published_at"],
        "reference": item["external_ref"],
        "images": len(item["images"]),
        "likes": item["like_count"],
        "page": ctx.site.page(item),
    }
