# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""``aipress24 press-release``."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

from cyclopts import App, Parameter

from .. import ApiError
from .context import Context, Ctx
from .document import Document
from .errors import CliError, UsageError
from .plan import Action, Plan, Remote, make_plan
from .send import publish as publish_remote
from .send import send
from .site import COLLECTION, NETWORK_ERRORS, Site
from .sources import is_item, select
from .state import State

KIND = "press-release"
NOUN = "press release(s)"

app = App(name=KIND, help="Your press releases.")

Flag = Parameter(negative="")
Sources = Annotated[
    Path,
    Parameter(help="Documents, folders holding one, or catalogs.", negative=""),
]
Targets = Annotated[
    str,
    Parameter(
        help="Documents, folders or catalogs; or ids or URLs of press releases.",
        negative="",
    ),
]
Only = Annotated[
    list[str] | None,
    Parameter(help="Only the sources or references like this pattern.", negative=""),
]
Limit = Annotated[int | None, Parameter(help="At most this many documents.")]
SkipInvalid = Annotated[bool, Flag, Parameter(help="Send the valid documents.")]
Overwrite = Annotated[
    bool, Flag, Parameter(help="Replace what was also changed on the site.")
]
Recreate = Annotated[
    bool, Flag, Parameter(help="Create again what was deleted on the site.")
]
DryRun = Annotated[bool, Flag, Parameter(help="Show what would be done.")]
Yes = Annotated[bool, Flag, Parameter(help="Do not ask for a confirmation.")]


# --- reading ---------------------------------------------------------------


@app.command
def check(*sources: Sources, only: Only = None, limit: Limit = None, ctx: Ctx) -> None:
    """Report every problem of every document, sending nothing about them."""
    documents = _select(ctx, sources, only, limit)
    if ctx.has_token:
        documents = [ctx.site.resolve(document) for document in documents]
    else:
        ctx.say("No token: classification and publisher were not checked.")
    for document in documents:
        missing = tuple(Plan(document, Action.CREATE).publish_problems())
        if document.problems:
            result, problems = "invalid", (*document.problems, *missing)
        else:
            result, problems = ("draft-only" if missing else "ready"), missing
        ctx.result(
            result,
            document.title,
            str(document.source),
            ok=not document.problems,
            problems=problems,
            warnings=document.warnings,
            **_identity(document),
        )
    ctx.summary(NOUN)


@app.command
def status(*sources: Sources, only: Only = None, limit: Limit = None, ctx: Ctx) -> None:
    """Compare each document with the site."""
    for plan in _plans(ctx, _select(ctx, sources, only, limit)):
        show_status(ctx, plan)
    ctx.summary(NOUN)


def show_status(ctx: Context, plan: Plan) -> None:
    if plan.document.problems:
        _report_invalid(ctx, plan.document, plan.document.problems)
        return
    remote = plan.remote
    detail = f"{remote.item['status']}  {ctx.site.page(remote.item)}" if remote else ""
    _report(ctx, plan.action.value, plan, remote, detail=detail, ok=True)


@app.command(name="list")
def list_(*, public: Annotated[bool, Flag] = False, ctx: Ctx) -> None:
    """List your press releases.

    Parameters
    ----------
    public
        List everyone's public ones instead.
    """
    if public:
        for item in ctx.site.client.iter("press-releases", limit=100):
            date = (item["published_at"] or "")[:10]
            ctx.line(f"{item['id']}  {date:<10}  {item['title']}", item)
        return
    for item in ctx.site.items:
        date = (item["published_at"] or "")[:10]
        text = f"{item['id']}  {item['status']:<8}  {date:<10}  {item['titre']}"
        ctx.line(text, _describe(ctx, item))


@app.command
def show(*targets: Targets, ctx: Ctx) -> None:
    """Show press releases, as they are on the site."""
    for item in _items(ctx, targets):
        details = _describe(ctx, item)
        ctx.line(
            "\n".join(f"{key}: {value}" for key, value in details.items()), details
        )


# --- writing ---------------------------------------------------------------


@app.command
def draft(
    *sources: Sources,
    only: Only = None,
    limit: Limit = None,
    skip_invalid: SkipInvalid = False,
    overwrite: Overwrite = False,
    recreate: Recreate = False,
    dry_run: DryRun = False,
    ctx: Ctx,
) -> None:
    """Have each document on the site, as a draft.

    What is already public is left alone.
    """
    documents = _select(ctx, sources, only, limit)
    plans = _plans(ctx, documents, overwrite=overwrite, recreate=recreate)
    plans = _valid(ctx, plans, skip_invalid=skip_invalid, dry_run=dry_run)
    for plan in plans:
        if dry_run:
            _report(ctx, plan.action.value, plan, plan.remote, ok=True)
        elif plan.is_public and plan.action is not Action.CONFLICT:
            is_current = plan.action in (Action.NOTHING, Action.KEEP)
            detail = "" if is_current else "changed here: use publish to update it"
            _report(ctx, "public", plan, plan.remote, detail=detail, ok=is_current)
        else:
            _attempt(ctx, plan, publishing=False)
    _finish(ctx)


@app.command
def publish(
    *targets: Targets,
    only: Only = None,
    limit: Limit = None,
    skip_invalid: SkipInvalid = False,
    overwrite: Overwrite = False,
    recreate: Recreate = False,
    dry_run: DryRun = False,
    yes: Yes = False,
    ctx: Ctx,
) -> None:
    """Have each document public, sending what changed.

    Given an id or a URL, publish what is on the site, sending nothing.
    """
    if _are_items(targets):
        _change_items(ctx, targets, "publish", dry_run=dry_run, yes=yes)
        return
    documents = _select(ctx, [Path(target) for target in targets], only, limit)
    plans = [
        replace(plan, document=plan.document.with_problems(*plan.publish_problems()))
        for plan in _plans(ctx, documents, overwrite=overwrite, recreate=recreate)
    ]
    plans = _valid(ctx, plans, skip_invalid=skip_invalid, dry_run=dry_run)
    if dry_run:
        ctx.say(_publication_summary(ctx, plans))
        for plan in plans:
            _report(ctx, plan.action.value, plan, plan.remote, ok=True)
        ctx.summary(NOUN)
        return
    if any(_will_be_seen(plan) for plan in plans):
        ctx.confirm(_publication_summary(ctx, plans), yes=yes)
    for plan in plans:
        _attempt(ctx, plan, publishing=True)
    _finish(ctx)


@app.command
def unpublish(
    *targets: Targets, dry_run: DryRun = False, yes: Yes = False, ctx: Ctx
) -> None:
    """Have each press release a draft again."""
    _change_items(ctx, targets, "unpublish", dry_run=dry_run, yes=yes)


@app.command
def delete(
    *targets: Targets, dry_run: DryRun = False, yes: Yes = False, ctx: Ctx
) -> None:
    """Delete press releases from the site, for good."""
    _change_items(ctx, targets, "delete", dry_run=dry_run, yes=yes)


# --- documents -------------------------------------------------------------


def _select(
    ctx: Context,
    sources: Sequence[Path],
    only: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[Document]:
    if not sources:
        raise UsageError("Give at least one document, folder or catalog.")
    if any(is_item(str(source)) for source in sources):
        raise UsageError("This command takes documents, not ids or URLs.")
    selection = select(sources, KIND, only or (), limit)
    if selection.left_out:
        counts = ", ".join(f"{n} {name}" for name, n in selection.left_out.items())
        ctx.say(f"Left out: {counts}.")
    return selection.documents


def _plans(
    ctx: Context,
    documents: Sequence[Document],
    *,
    overwrite: bool = False,
    recreate: bool = False,
) -> list[Plan]:
    return [
        plan_document(ctx.site, document, overwrite=overwrite, recreate=recreate)
        for document in documents
    ]


def plan_document(
    site: Site, document: Document, *, overwrite: bool = False, recreate: bool = False
) -> Plan:
    if not document.reference:
        return Plan(document, Action.CREATE)
    document = site.resolve(document)
    entry = State(document.home, site.url).get(document.reference)
    remote = site.find_remote(entry.id if entry else None, document.reference)
    return make_plan(document, entry, remote, overwrite=overwrite, recreate=recreate)


def _valid(
    ctx: Context, plans: Sequence[Plan], *, skip_invalid: bool, dry_run: bool
) -> list[Plan]:
    """Report the invalid documents; return the others."""
    invalid = [plan for plan in plans if plan.document.problems]
    for plan in invalid:
        _report_invalid(ctx, plan.document, plan.document.problems)
    if invalid and not skip_invalid and not dry_run:
        raise CliError(
            f"Nothing was sent: {len(invalid)} of {len(plans)} documents are invalid. "
            "Use --skip-invalid to send the others."
        )
    return [plan for plan in plans if not plan.document.problems]


def _attempt(ctx: Context, plan: Plan, *, publishing: bool) -> None:
    """Send one document, and report what became of it."""
    if plan.action in (Action.CONFLICT, Action.DELETED):
        _report(ctx, plan.action.value, plan, plan.remote, ok=False)
        return
    state = State(plan.document.home, ctx.site.url)
    remote = plan.remote
    try:
        remote = send(ctx.site, state, plan)
        result = _SENT[plan.action]
        if publishing and not remote.is_public:
            remote = publish_remote(ctx.site, state, plan, remote.id)
            result = "published"
    except ApiError as error:
        if error.status == 401:
            raise
        _report(ctx, "failed", plan, remote, detail=api_message(error), ok=False)
    except NETWORK_ERRORS as error:
        _report(ctx, "failed", plan, remote, detail=str(error), ok=False)
    else:
        _report(ctx, result, plan, remote, ok=True)


_SENT = {
    Action.CREATE: "created",
    Action.UPDATE: "updated",
    Action.NOTHING: "unchanged",
    Action.KEEP: "kept",
}


def _will_be_seen(plan: Plan) -> bool:
    if plan.action in (Action.CONFLICT, Action.DELETED):
        return False
    return not plan.is_public or plan.action is Action.UPDATE


def _publication_summary(ctx: Context, plans: Sequence[Plan]) -> str:
    visible = [plan for plan in plans if _will_be_seen(plan)]
    publishers = {plan.document.fields["publisher_id"] for plan in visible}
    names = ", ".join(sorted(_publisher_name(ctx.site, each) for each in publishers))
    groups = {
        "to create": [p for p in visible if p.action is Action.CREATE],
        "draft(s) to publish": [
            p for p in visible if p.action is not Action.CREATE and not p.is_public
        ],
        "public text(s) to update": [p for p in visible if p.is_public],
    }
    lines = [
        f"Publish {len(visible)} {NOUN} on {ctx.site.url}, for {names or 'no one'}:"
    ]
    lines += [f"  {len(group)} {name}" for name, group in groups.items() if group]
    dates = sorted(
        plan.document.fields["published_at"][:10]
        for plan in visible
        if "published_at" in plan.document.fields
    )
    if dates:
        lines.append(f"  dated from {dates[0]} to {dates[-1]}")
    if len(dates) < len(visible):
        lines.append(f"  {len(visible) - len(dates)} without a date: as of now")
    return "\n".join(lines)


def _publisher_name(site: Site, identifier: int) -> str:
    return site.publishers.get(identifier, str(identifier))


def _finish(ctx: Context) -> None:
    hints = []
    if ctx.results["conflict"]:
        hints.append("--overwrite replaces what was also changed on the site.")
    if ctx.results["deleted"]:
        hints.append("--recreate creates again what was deleted on the site.")
    if ctx.results["failed"]:
        hints.append("Run the same command again to do what is left.")
    ctx.summary(NOUN, *hints)


def _identity(document: Document) -> dict[str, Any]:
    return {"source": str(document.source), "reference": document.reference}


def _report_invalid(
    ctx: Context, document: Document, problems: tuple[str, ...]
) -> None:
    ctx.result(
        "invalid",
        document.title,
        str(document.source),
        ok=False,
        problems=problems,
        **_identity(document),
    )


def _report(
    ctx: Context,
    result: str,
    plan: Plan,
    remote: Remote | None,
    *,
    ok: bool,
    detail: str = "",
) -> None:
    page = ctx.site.page(remote.item) if remote else ""
    problems = []
    if plan.action is Action.CONFLICT:
        problems.append(_conflict(plan))
    ctx.result(
        result,
        plan.document.title,
        detail or page,
        ok=ok,
        problems=tuple(problems),
        **_identity(plan.document),
        id=remote.id if remote else None,
        status=remote.item["status"] if remote else None,
        page=page or None,
    )


def _conflict(plan: Plan) -> str:
    if plan.entry is None:
        return "already on the site, but not sent from here"
    here, there = ", ".join(plan.changed_here), ", ".join(plan.changed_there)
    return f"changed here: {here}; on the site: {there}"


# --- items -----------------------------------------------------------------


def _are_items(targets: Sequence[str]) -> bool:
    kinds = {is_item(target) for target in targets}
    if len(kinds) > 1:
        raise UsageError("Give either documents, or ids and URLs, not both.")
    return kinds == {True}


def _items(ctx: Context, targets: Sequence[str]) -> list[dict[str, Any]]:
    """The items given, or those of the documents given."""
    if not targets:
        raise UsageError("Give at least one document, catalog, id or URL.")
    if _are_items(targets):
        return [ctx.site.find_item(target) for target in targets]
    items = []
    for document in _select(ctx, [Path(target) for target in targets]):
        entry = (
            State(document.home, ctx.site.url).get(document.reference)
            if document.reference
            else None
        )
        remote = (
            ctx.site.find_remote(entry.id if entry else None, document.reference)
            if document.reference
            else None
        )
        if remote:
            items.append(dict(remote.item))
        else:
            ctx.result("absent", document.title, **_identity(document))
    return items


def _change_items(
    ctx: Context, targets: Sequence[str], verb: str, *, dry_run: bool, yes: bool
) -> None:
    done, unchanged_status = _VERBS[verb]
    items = _items(ctx, targets)
    todo = [item for item in items if item["status"] != unchanged_status]
    if todo:
        titles = "\n".join(f"  {item['titre']}" for item in todo)
        question = (
            f"{verb.capitalize()} {len(todo)} {NOUN} on {ctx.site.url}:\n{titles}"
        )
        if dry_run:
            ctx.say(question)
            return
        ctx.confirm(question, yes=yes)
    for item in items:
        if item["status"] == unchanged_status:
            _report_item(ctx, "unchanged", item)
            continue
        try:
            after = _apply(ctx.site, verb, item)
        except (ApiError, *NETWORK_ERRORS) as error:
            if isinstance(error, ApiError) and error.status == 401:
                raise
            detail = api_message(error) if isinstance(error, ApiError) else str(error)
            _report_item(ctx, "failed", item, detail=detail, ok=False)
        else:
            _report_item(ctx, done, after)
    _finish(ctx)


_VERBS = {
    "publish": ("published", "public"),
    "unpublish": ("draft", "draft"),
    "delete": ("deleted", None),
}


def _apply(site: Site, verb: str, item: dict[str, Any]) -> dict[str, Any]:
    match verb:
        case "publish":
            return site.client.publish(COLLECTION, item["id"])
        case "unpublish":
            return site.client.unpublish(COLLECTION, item["id"])
        case _:
            site.client.delete(COLLECTION, item["id"])
            return {**item, "status": None, "_links": {}}


def _report_item(
    ctx: Context,
    result: str,
    item: dict[str, Any],
    *,
    detail: str = "",
    ok: bool = True,
) -> None:
    page = ctx.site.page(item)
    ctx.result(
        result,
        item["titre"],
        detail or page,
        ok=ok,
        id=item["id"],
        reference=item.get("external_ref"),
        status=item["status"],
        page=page or None,
    )


def _describe(ctx: Context, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "title": item["titre"],
        "status": item["status"],
        "published_at": item["published_at"],
        "publisher_id": item["publisher_id"],
        "reference": item.get("external_ref"),
        "genre": item["genre"],
        "section": item["section"],
        "topic": item["topic"],
        "sector": item["sector"],
        "page": ctx.site.page(item),
    }


def api_message(error: ApiError) -> str:
    details = error.payload.get("errors")
    return (
        f"{error} {json.dumps(details, ensure_ascii=False)}" if details else f"{error}"
    )
