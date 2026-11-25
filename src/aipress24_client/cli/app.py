# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The ``aipress24`` command: options common to all, and the small nouns."""

from __future__ import annotations

import getpass
import sys
import urllib.error
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, CycloptsError, Parameter

from .. import DEFAULT_BASE_URL, ApiError, __version__
from . import catalog, press_release
from .access import find_token, forget_token, store_token
from .context import Context, Ctx
from .document import CLASSIFICATION
from .errors import CliError, UsageError
from .press_release import api_message, plan_document, show_status
from .sources import load_row
from .vocabulary import search as search_values

INTERRUPTED = 130

app = App(
    name="aipress24",
    help="Publish existing documents on AIpress24.",
    version=__version__,
    result_action="return_value",
    exit_on_error=False,
)
catalog_app = App(name="catalog", help="The table in which documents are sorted.")
vocabulary_app = App(name="vocabulary", help="The values a classification accepts.")
publisher_app = App(name="publisher", help="The organisations you may publish for.")
auth_app = App(name="auth", help="Your access to the site.")
for noun in (press_release.app, catalog_app, vocabulary_app, publisher_app, auth_app):
    app.command(noun)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command and return its exit status."""
    try:
        return app.meta(argv) or 0
    except CycloptsError:  # Cyclopts has already printed it.
        return UsageError.exit_status
    except CliError as error:
        status, message = error.exit_status, str(error)
    except ApiError as error:
        status, message = CliError.exit_status, api_message(error)
        if error.status == 401:
            message = f"The site refused the token ({message})."
    except KeyboardInterrupt:
        status, message = INTERRUPTED, "Interrupted. Run it again to do what is left."
    except (OSError, ValueError) as error:
        status, message = CliError.exit_status, str(error)
    print(f"error: {message}", file=sys.stderr)
    return status


@app.meta.default
def launch(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    site: Annotated[str, Parameter(env_var="AIPRESS24_SITE")] = DEFAULT_BASE_URL,
    json: Annotated[bool, Parameter(negative="")] = False,
) -> int:
    """Publish existing documents on AIpress24.

    Parameters
    ----------
    site
        The site to talk to.
    json
        Print the results for programs, one JSON object per line.
    """
    command, bound, injected = app.parse_args(tokens)
    ctx = Context(site.rstrip("/"), as_json=json)
    if "ctx" in injected:
        bound.arguments["ctx"] = ctx
    try:
        command(*bound.args, **bound.kwargs)
    except urllib.error.URLError as error:
        raise CliError(f"Cannot reach {site}: {error.reason}") from error
    return CliError.exit_status if ctx.failed else 0


# --- catalog ---------------------------------------------------------------


@catalog_app.command(name="create")
def catalog_create(
    *paths: Path,
    output: Annotated[Path, Parameter(alias="-o")],
    ctx: Ctx,
) -> None:
    """List documents in a new table.

    Parameters
    ----------
    paths
        Documents, or folders to look into.
    output
        The CSV file to write.
    """
    _require_paths(paths)
    count = catalog.create(output, paths)
    ctx.line(f"{output}: {count} documents", {"catalog": str(output), "added": count})
    ctx.say(f"Give each one a type: {', '.join(catalog.TYPES)}.")


@catalog_app.command(name="update")
def catalog_update(table: Path, /, *paths: Path, ctx: Ctx) -> None:
    """Add the documents a table does not list yet, changing no line of it.

    Parameters
    ----------
    table
        The catalog.
    paths
        Documents, or folders to look into.
    """
    _require_paths(paths)
    count = catalog.update(table, paths)
    ctx.line(f"{table}: {count} added", {"catalog": str(table), "added": count})


@catalog_app.command(name="status")
def catalog_status(table: Path, /, *, ctx: Ctx) -> None:
    """Show the type of each document, and compare it with the site."""
    for row in catalog.read_rows(table):
        document = load_row(table, row)
        if row.type == press_release.KIND:
            show_status(ctx, plan_document(ctx.site, document))
        else:
            kind = row.type or "undecided"
            ctx.result(
                kind,
                document.title,
                str(row.source),
                source=str(row.source),
                reference=document.reference,
            )
    ctx.summary("documents")


def _require_paths(paths: Sequence[Path]) -> None:
    if not paths:
        raise UsageError("Give at least one document or folder.")


# --- vocabulary, publisher -------------------------------------------------


@vocabulary_app.command(name="list")
def vocabulary_list(
    name: Literal[
        "press-release.genre",
        "press-release.section",
        "press-release.topic",
        "press-release.sector",
    ],
    /,
    *,
    ctx: Ctx,
) -> None:
    """List the values of a vocabulary."""
    for value in ctx.site.vocabularies[name.partition(".")[2]]:
        ctx.line(value, {"vocabulary": name, "value": value})


@vocabulary_app.command(name="search")
def vocabulary_search(text: str, /, *, ctx: Ctx) -> None:
    """Look for a text in every vocabulary, ignoring case and accents."""
    for field in CLASSIFICATION:
        name = f"{press_release.KIND}.{field}"
        for value in search_values(text, ctx.site.vocabularies[field]):
            ctx.line(f"{name}  {value}", {"vocabulary": name, "value": value})


@publisher_app.command(name="list")
def publisher_list(*, ctx: Ctx) -> None:
    """List the organisations you may publish press releases for."""
    for identifier, name in ctx.site.publishers.items():
        ctx.line(f"{identifier}  {name}", {"id": identifier, "name": name})
    if not ctx.site.publishers:
        ctx.say("None: your account has no organisation.")


# --- auth ------------------------------------------------------------------


@auth_app.command(name="login")
def auth_login(*, ctx: Ctx) -> None:
    """Store your API token for this site, after verifying it."""
    if sys.stdin.isatty():
        token = getpass.getpass("API token: ").strip()
    else:
        token = sys.stdin.readline().strip()
    if not token:
        raise UsageError("No token was given.")
    name = ctx.make_client(token).me()["full_name"]
    path = store_token(ctx.site_url, token)
    ctx.line(f"Logged in as {name} on {ctx.site_url}.", {"name": name})
    ctx.say(f"The token is in {path}.")


@auth_app.command(name="logout")
def auth_logout(*, ctx: Ctx) -> None:
    """Forget your API token for this site."""
    if not forget_token(ctx.site_url):
        raise CliError(f"No token is stored for {ctx.site_url}.")
    ctx.say("Forgotten here. It stays valid until you revoke it on the site.")


@auth_app.command(name="status")
def auth_status(*, ctx: Ctx) -> None:
    """Show the account, and the organisations it may publish for."""
    if not find_token(ctx.site_url):
        raise CliError("No token: run 'aipress24 auth login', or set AIPRESS24_TOKEN.")
    me = ctx.site.client.me()
    details = {
        "site": ctx.site_url,
        "account": me["full_name"],
        "organisation": me["organisation_name"] or None,
        "publishers": len(ctx.site.publishers),
    }
    ctx.line("\n".join(f"{key}: {value}" for key, value in details.items()), details)
