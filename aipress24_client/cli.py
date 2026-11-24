# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Create and update press releases from folders (``aipress24`` command).

A folder holds one Markdown file, with a YAML front matter, and its images.
``.aipress24.json``, written next to them, remembers which release the folder
was pushed to.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import urllib.error
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import DEFAULT_BASE_URL, ApiError, Client, PressReleaseImage

try:
    import yaml
    from markdown_it import MarkdownIt
except ModuleNotFoundError as error:
    msg = f"{error}. Install the command with: uv tool install 'aipress24-client[cli]'"
    raise SystemExit(msg) from error

COLLECTION = "me/press-releases"
STATE_FILE = ".aipress24.json"
MAX_IMAGE_SIZE = 4 * 1024 * 1024

TEXT_FIELDS = (
    "titre",
    "chapo",
    "genre",
    "section",
    "topic",
    "sector",
    "geo_localisation",
    "language",
    "address",
    "pays_zip_ville",
    "pays_zip_ville_detail",
)
CLASSIFICATION = ("genre", "section", "topic", "sector")
REQUIRED_TO_PUBLISH = ("titre", "contenu", *CLASSIFICATION)
FRONT_MATTER_KEYS = {*TEXT_FIELDS, "publisher_id", "embargoed_until", "images"}
IMAGE_KEYS = {"file", "caption", "copyright"}


class CliError(Exception):
    """A problem to show the user, without a traceback."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command and return its exit status."""
    args = _parser().parse_args(argv)
    try:
        args.run(args)
    except CliError as error:
        message = str(error)
    except ApiError as error:
        message = _api_message(error)
    except urllib.error.URLError as error:
        message = f"Cannot reach {args.base_url}: {error.reason}"
    except (OSError, ValueError) as error:
        message = str(error)
    else:
        return 0
    print(f"error: {message}", file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aipress24", description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AIPRESS24_URL", DEFAULT_BASE_URL),
        help="site to talk to (default: $AIPRESS24_URL, or %(default)s)",
    )
    commands = parser.add_subparsers(required=True, metavar="COMMAND")

    check = commands.add_parser("check", help="validate a folder, sending nothing")
    check.set_defaults(run=run_check)

    push = commands.add_parser("push", help="create or update the release, as a draft")
    push.add_argument("--publish", action="store_true", help="publish it afterwards")
    push.add_argument(
        "--force", action="store_true", help="overwrite changes made on the site"
    )
    push.set_defaults(run=run_push)

    status = commands.add_parser("status", help="show the state of the release")
    status.set_defaults(run=run_status)

    for command in (check, push, status):
        command.add_argument("folder", type=Path)

    values = commands.add_parser("values", help="list the accepted classification")
    values.add_argument("field", choices=CLASSIFICATION)
    values.set_defaults(run=run_values)
    return parser


# --- commands -------------------------------------------------------------


def run_check(args: argparse.Namespace) -> None:
    release = load_release(args.folder)
    token = find_token()
    if token:
        check_classification(release, Client(token, args.base_url))
    else:
        print("No token: the classification was not compared with the site's.")
    missing = release.missing_to_publish()
    if missing:
        print(f"Valid as a draft. Missing to publish: {', '.join(missing)}.")
    else:
        print("Ready to publish.")


def run_push(args: argparse.Namespace) -> None:
    release = load_release(args.folder)
    missing = release.missing_to_publish()
    if args.publish and missing:
        raise CliError(f"Missing to publish: {', '.join(missing)}.")
    client = make_client(args)
    check_classification(release, client)
    push(client, args.folder, release, publish=args.publish, force=args.force)


def run_status(args: argparse.Namespace) -> None:
    client = make_client(args)
    state = load_state(args.folder, client.base_url)
    if state is None:
        print("Never pushed.")
        return
    remote = fetch(client, state)
    print(f"{remote['status']}: {remote['titre']} (id {remote['id']})")
    if is_changed(remote, state):
        print("Changed on the site since the last push.")


def run_values(args: argparse.Namespace) -> None:
    for value in make_client(args).press_release_vocabularies()[args.field]:
        print(value)


# --- pushing --------------------------------------------------------------


def push(
    client: Client, folder: Path, release: Release, *, publish: bool, force: bool
) -> None:
    """Make the site's release match the folder's."""
    state = load_state(folder, client.base_url)
    if state is None:
        remote = client.create(COLLECTION, release.fields)
        identifier = remote["id"]
        print(f"Created draft {identifier}.")
        save_state(folder, State(client.base_url, identifier))
    else:
        identifier = state.id
        remote = fetch(client, state)
        if is_changed(remote, state) and not force:
            raise CliError(
                "The release was changed on the site since the last push. "
                "Use --force to overwrite it."
            )
        # An interrupted push leaves no date, so that it can be run again.
        save_state(folder, State(client.base_url, identifier))
        client.update(COLLECTION, identifier, release.fields)
        print(f"Updated {identifier}.")

    push_images(client, identifier, release.images)
    if publish and remote["status"] != "public":
        client.publish(COLLECTION, identifier)
        print("Published.")

    remote = client.get_one(COLLECTION, identifier)
    save_state(folder, State(client.base_url, identifier, remote["modified_at"]))


def push_images(client: Client, identifier: int, images: Sequence[Image]) -> None:
    """Make the carousel match ``images``, in order.

    The API only appends, so everything after the first difference is replaced.
    """
    current = client.press_release_images(identifier)
    kept = 0
    for image, uploaded in zip(images, current):
        if not image.matches(uploaded):
            break
        kept += 1
    for uploaded in current[kept:]:
        client.delete_press_release_image(identifier, uploaded["id"])
    for image in images[kept:]:
        client.add_press_release_image(
            identifier, image.content, image.name, image.caption, image.copyright
        )
    if kept < len(current) or kept < len(images):
        print(f"Images: {kept} kept, {len(images) - kept} sent.")


def fetch(client: Client, state: State) -> dict[str, Any]:
    try:
        return client.get_one(COLLECTION, state.id)
    except ApiError as error:
        if error.status != 404:
            raise
        raise CliError(
            f"Release {state.id} is not on the site any more. "
            f"Remove {STATE_FILE} to create it again."
        ) from error


def is_changed(remote: dict[str, Any], state: State) -> bool:
    return state.modified_at not in (None, remote["modified_at"])


def check_classification(release: Release, client: Client) -> None:
    accepted: dict[str, list[str]] = {**client.press_release_vocabularies()}
    for field in CLASSIFICATION:
        value = release.fields.get(field)
        if value and value not in accepted[field]:
            raise CliError(
                f"{field}: {value!r} is not accepted. "
                f"See the values with: aipress24 values {field}"
            )


# --- the folder -----------------------------------------------------------


@dataclass(frozen=True)
class Image:
    """An image of the carousel, as found in the folder."""

    name: str
    content: bytes
    caption: str
    copyright: str

    def matches(self, uploaded: PressReleaseImage) -> bool:
        return (
            hashlib.sha256(self.content).hexdigest(),
            self.caption,
            self.copyright,
        ) == (uploaded["sha256"], uploaded["caption"], uploaded["copyright"])


@dataclass(frozen=True)
class Release:
    """A press release, as found in the folder."""

    fields: dict[str, Any]
    images: tuple[Image, ...]

    def missing_to_publish(self) -> list[str]:
        return [
            field
            for field in REQUIRED_TO_PUBLISH
            if not self.fields.get(field, "").strip()
        ]


def load_release(folder: Path) -> Release:
    """Read and validate the folder."""
    if not folder.is_dir():
        raise CliError(f"{folder} is not a folder.")
    sources = sorted(folder.glob("*.md"))
    if len(sources) != 1:
        raise CliError(f"{folder} must contain one .md file, not {len(sources)}.")
    text = sources[0].read_text(encoding="utf-8-sig")
    matter, body = _split_front_matter(text)

    unknown = sorted(str(key) for key in matter.keys() - FRONT_MATTER_KEYS)
    if unknown:
        raise CliError(f"Unknown front matter: {', '.join(unknown)}.")
    fields: dict[str, Any] = {
        key: _text(key, value) for key, value in matter.items() if key in TEXT_FIELDS
    }
    if not fields.get("titre", ""):
        raise CliError("The front matter must give a titre.")
    if "publisher_id" in matter:
        fields["publisher_id"] = _publisher(matter["publisher_id"])
    if "embargoed_until" in matter:
        fields["embargoed_until"] = _embargo(matter["embargoed_until"])
    fields["contenu"] = _html(body)

    entries = matter.get("images") or []
    if not isinstance(entries, list):
        raise CliError("images: expected a list.")
    root = folder.resolve()
    return Release(fields, tuple(_load_image(root, entry) for entry in entries))


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    markers = [index for index, line in enumerate(lines) if line.rstrip() == "---"]
    if len(markers) < 2 or markers[0] != 0:
        raise CliError("The file must start with a front matter between two '---'.")
    try:
        matter = yaml.safe_load("".join(lines[1 : markers[1]]))
    except yaml.YAMLError as error:
        raise CliError(f"Invalid front matter: {error}") from error
    if not isinstance(matter, dict):
        raise CliError("The front matter must be a list of 'key: value' lines.")
    return matter, "".join(lines[markers[1] + 1 :])


def _text(key: str, value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CliError(f"{key}: {value!r} is not a text, put it between quotes.")
    return value.strip()


def _publisher(value: object) -> int | None:
    if value is None or type(value) is int:
        return value
    raise CliError("publisher_id: expected a number.")


def _embargo(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CliError(
            "embargoed_until: expected a date, a time and a time zone, "
            "as in 2026-12-01T08:00:00+01:00."
        )
    return value.isoformat()


def _html(body: str) -> str:
    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    images = [
        child
        for token in markdown.parse(body)
        for child in token.children or []
        if child.type == "image"
    ]
    if images:
        raise CliError("Images are not supported in the text: list them in images.")
    return str(markdown.render(body)).strip()


def _load_image(root: Path, entry: object) -> Image:
    if isinstance(entry, str):
        entry = {"file": entry}
    if not isinstance(entry, dict) or "file" not in entry or entry.keys() - IMAGE_KEYS:
        raise CliError(f"images: expected file, caption and copyright, not {entry!r}.")
    name = _text("file", entry["file"])
    path = (root / name).resolve()
    # Resolved, so that neither '..' nor a link can send a file from elsewhere.
    if not path.is_relative_to(root):
        raise CliError(f"{name} is outside the folder.")
    if not path.is_file():
        raise CliError(f"{name} does not exist.")
    if path.stat().st_size >= MAX_IMAGE_SIZE:
        raise CliError(f"{name} is too large: the limit is 4 MB.")
    return Image(
        path.name,
        path.read_bytes(),
        _text("caption", entry.get("caption")),
        _text("copyright", entry.get("copyright")),
    )


# --- what the folder was pushed to ----------------------------------------


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


# --- token and messages ---------------------------------------------------


def make_client(args: argparse.Namespace) -> Client:
    token = find_token()
    if not token:
        raise CliError(f"No token: set AIPRESS24_TOKEN, or write it in {_token_file()}")
    return Client(token, args.base_url)


def find_token() -> str:
    """Return the configured token, or an empty string when there is none."""
    token = os.environ.get("AIPRESS24_TOKEN", "").strip()
    if token:
        return token
    path = _token_file()
    if not path.exists():
        return ""
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise CliError(f"{path} is readable by others. Run: chmod 600 {path}")
    return path.read_text(encoding="utf-8").strip()


def _token_file() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "aipress24" / "token"


def _api_message(error: ApiError) -> str:
    details = error.payload.get("errors")
    return (
        f"{error} {json.dumps(details, ensure_ascii=False)}" if details else f"{error}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
