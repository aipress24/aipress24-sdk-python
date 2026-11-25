# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Make the site's press release match a folder."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .. import ApiError, Client
from .errors import CliError
from .release import CLASSIFICATION, Image, Release
from .state import STATE_FILE, State, load_state, save_state

COLLECTION = "me/press-releases"


def push(
    client: Client, folder: Path, release: Release, *, publish: bool, force: bool
) -> None:
    """Make the site's release match the folder's."""
    state = load_state(folder, client.base_url)
    if state is None:
        remote = client.create(COLLECTION, release.fields)
        identifier = remote["id"]
        print(f"Created draft: {page_url(client, identifier)}")
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
        print(f"Updated: {page_url(client, identifier)}")

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
    for image, uploaded in zip(images, current, strict=False):
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


def page_url(client: Client, identifier: int) -> str:
    """The author's page of a release, draft or published."""
    # The API does not link to the site's pages.
    return f"{client.base_url}/wip/communiques/{identifier}/"


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
