# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Carry out the plans, one document at a time."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .document import Image
from .plan import Action, Plan, Remote, local_values
from .site import COLLECTION, Site
from .state import Entry, State, digests


def send(site: Site, state: State, plan: Plan) -> Remote:
    """Make the site hold the document, as a draft or as it is."""
    document = plan.document
    reference = document.reference
    if plan.action is Action.CREATE:
        # Noted first: if the answer is lost, the release found by this
        # reference the next time is known to be ours.
        state.save(reference, Entry())
        created = site.client.create(COLLECTION, dict(document.fields))
        identifier = created["id"]
    else:
        identifier = _existing(plan).id
    if plan.action is Action.UPDATE:
        state.save(reference, Entry(identifier))
        site.client.update(COLLECTION, identifier, dict(document.fields))
    if plan.action in (Action.CREATE, Action.UPDATE):
        state.save(reference, Entry(identifier))
        _send_images(site, identifier, document.images)
        return _remember(site, state, plan, identifier)
    return _existing(plan)


def publish(site: Site, state: State, plan: Plan, identifier: int) -> Remote:
    """Publish what the site holds."""
    site.client.publish(COLLECTION, identifier)
    if plan.action is Action.KEEP:
        return site.read(identifier)
    return _remember(site, state, plan, identifier)


def _existing(plan: Plan) -> Remote:
    if plan.remote is None:
        msg = f"{plan.action} without a release on the site"
        raise AssertionError(msg)
    return plan.remote


def _remember(site: Site, state: State, plan: Plan, identifier: int) -> Remote:
    document = plan.document
    remote = site.read(identifier)
    entry = Entry(
        identifier,
        sent=digests(local_values(document)),
        site=digests(remote.values(document)),
    )
    state.save(document.reference, entry)
    return remote


def _send_images(site: Site, identifier: int, images: Sequence[Image]) -> None:
    """Make the carousel match ``images``, in order.

    The API only appends, so everything after the first difference is replaced.
    """
    client = site.client
    current: Sequence[Any] = client.press_release_images(identifier)
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
