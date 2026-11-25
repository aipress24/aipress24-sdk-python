# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The commands and their options."""

from __future__ import annotations

import json
import sys
import urllib.error
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, CycloptsError, Parameter

from .. import DEFAULT_BASE_URL, ApiError, Client, __version__
from .errors import CliError
from .release import load_release
from .state import load_state
from .sync import check_classification, fetch, is_changed, page_url, push
from .token import find_token, token_file

USAGE_ERROR = 2

Flag = Parameter(negative="")
# Given by `launch`, which parses --base-url for every command.
BaseUrl = Annotated[str, Parameter(parse=False)]

app = App(
    name="aipress24",
    help="Create and update press releases from folders.",
    version=__version__,
    result_action="return_value",
    exit_on_error=False,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command and return its exit status."""
    try:
        app.meta(argv)
    except CycloptsError:  # Cyclopts has already printed it.
        return USAGE_ERROR
    except CliError as error:
        message = str(error)
    except ApiError as error:
        message = _api_message(error)
    except (OSError, ValueError) as error:
        message = str(error)
    else:
        return 0
    print(f"error: {message}", file=sys.stderr)
    return 1


@app.meta.default
def launch(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    base_url: Annotated[str, Parameter(env_var="AIPRESS24_URL")] = DEFAULT_BASE_URL,
) -> None:
    """Create and update press releases from folders.

    Parameters
    ----------
    base_url
        Site to talk to.
    """
    command, bound, injected = app.parse_args(tokens)
    if "base_url" in injected:
        bound.arguments["base_url"] = base_url
    try:
        command(*bound.args, **bound.kwargs)
    except urllib.error.URLError as error:
        raise CliError(f"Cannot reach {base_url}: {error.reason}") from error


# --- commands -------------------------------------------------------------


@app.command(name="check")
def run_check(folder: Path, /, *, base_url: BaseUrl) -> None:
    """Validate a folder, sending nothing about the release."""
    release = load_release(folder)
    token = find_token()
    if token:
        check_classification(release, Client(token, base_url))
    else:
        print("No token: the classification was not compared with the site's.")
    missing = release.missing_to_publish()
    if missing:
        print(f"Valid as a draft. Missing to publish: {', '.join(missing)}.")
    else:
        print("Ready to publish.")


@app.command(name="push")
def run_push(
    folder: Path,
    /,
    *,
    publish: Annotated[bool, Flag] = False,
    force: Annotated[bool, Flag] = False,
    base_url: BaseUrl,
) -> None:
    """Create or update the release, as a draft.

    Parameters
    ----------
    publish
        Publish it afterwards.
    force
        Overwrite changes made on the site.
    """
    release = load_release(folder)
    missing = release.missing_to_publish()
    if publish and missing:
        raise CliError(f"Missing to publish: {', '.join(missing)}.")
    client = make_client(base_url)
    check_classification(release, client)
    push(client, folder, release, publish=publish, force=force)


@app.command(name="status")
def run_status(folder: Path, /, *, base_url: BaseUrl) -> None:
    """Show the state of the release."""
    client = make_client(base_url)
    state = load_state(folder, client.base_url)
    if state is None:
        print("Never pushed.")
        return
    remote = fetch(client, state)
    print(f"{remote['status']}: {remote['titre']}")
    print(page_url(client, state.id))
    if is_changed(remote, state):
        print("Changed on the site since the last push.")


@app.command(name="values")
def run_values(
    field: Literal["genre", "section", "topic", "sector"], /, *, base_url: BaseUrl
) -> None:
    """List the accepted classification."""
    for value in make_client(base_url).press_release_vocabularies()[field]:
        print(value)


def make_client(base_url: str) -> Client:
    token = find_token()
    if not token:
        raise CliError(f"No token: set AIPRESS24_TOKEN, or write it in {token_file()}")
    return Client(token, base_url)


def _api_message(error: ApiError) -> str:
    details = error.payload.get("errors")
    return (
        f"{error} {json.dumps(details, ensure_ascii=False)}" if details else f"{error}"
    )
