# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The press releases of the user, on a site."""

from __future__ import annotations

import time
from dataclasses import replace
from functools import cached_property
from http.client import HTTPException
from typing import Any
from urllib.parse import urlsplit

from .. import ApiError, Client
from .document import Document, image_key
from .errors import CliError, UsageError
from .plan import Remote
from .vocabulary import closest

COLLECTION = "me/press-releases"
POSTS = "me/posts"
RETRY_DELAYS = (1, 3)
NETWORK_ERRORS = (OSError, HTTPException)


class RetryingClient(Client):
    """A client which repeats the reads that fail for a passing reason."""

    def _open(
        self,
        url: str,
        headers: dict[str, str],
        method: str = "GET",
        data: bytes | None = None,
    ) -> tuple[int, bytes]:
        for delay in RETRY_DELAYS if method == "GET" else ():
            try:
                status, body = super()._open(url, headers, method, data)
            except NETWORK_ERRORS:
                pass
            else:
                if status < 500:
                    return status, body
            time.sleep(delay)
        return super()._open(url, headers, method, data)


class Site:
    """What the commands need to know of a site, read once."""

    def __init__(self, client: Client) -> None:
        self.client = client

    @property
    def url(self) -> str:
        return self.client.base_url

    # --- releases ---------------------------------------------------------

    @cached_property
    def items(self) -> list[dict[str, Any]]:
        return list(self.client.iter(COLLECTION, limit=100))

    @cached_property
    def posts(self) -> list[dict[str, Any]]:
        try:
            return list(self.client.iter(POSTS, limit=100))
        except ApiError as error:
            if error.status == 404:
                msg = f"{self.url} does not offer what this command needs yet."
                raise CliError(msg) from error
            raise

    def find_item(self, target: str) -> dict[str, Any]:
        return self._find(target, self.items, "press releases")

    def find_post(self, target: str) -> dict[str, Any]:
        return self._find(target, self.posts, "posts")

    def _find(
        self, target: str, items: list[dict[str, Any]], noun: str
    ) -> dict[str, Any]:
        """The item with this id, or whose page has this URL."""
        if target.isdigit():
            found = [item for item in items if item["id"] == int(target)]
        else:
            path = urlsplit(target).path.rstrip("/")
            if not target.startswith(f"{self.url}/"):
                raise UsageError(f"{target} is not on {self.url}.")
            found = [
                item for item in items if urlsplit(page(item)).path.rstrip("/") == path
            ]
        if not found:
            raise CliError(f"{target} is not one of your {noun}.")
        return found[0]

    def find_remote(self, identifier: int | None, reference: str) -> Remote | None:
        by_id = {item["id"]: item for item in self.items}
        by_reference = {item.get("external_ref"): item for item in self.items}
        item = by_id.get(identifier) or by_reference.get(reference)
        return self.with_images(item) if item else None

    def with_images(self, item: dict[str, Any]) -> Remote:
        images = self.client.press_release_images(item["id"])
        return Remote(item, [list(image_key(image)) for image in images])

    def read(self, identifier: int) -> Remote:
        return self.with_images(self.client.get_one(COLLECTION, identifier))

    def page(self, item: Any) -> str:
        return self.url + page(item) if page(item) else ""

    # --- checking documents -----------------------------------------------

    @cached_property
    def vocabularies(self) -> dict[str, list[str]]:
        return {**self.client.press_release_vocabularies()}  # type: ignore[dict-item]

    @cached_property
    def publishers(self) -> dict[int, str]:
        try:
            return {item["id"]: item["name"] for item in self.client.publishers()}
        except ApiError as error:
            if error.status == 404:
                msg = f"{self.url} does not offer what this command needs yet."
                raise CliError(msg) from error
            raise

    @cached_property
    def own_publisher(self) -> int | None:
        return self.client.me().get("organisation_id")

    def resolve(self, document: Document) -> Document:
        """Check what depends on the site, and set the publisher."""
        problems = []
        for field, accepted in self.vocabularies.items():
            value = document.fields.get(field)
            if value and value not in accepted:
                problems.append(_refused(field, value, accepted))
        publisher = self._publisher_id(document.publisher)
        if publisher is None:
            problems.append(
                f"publisher: you may not publish for {document.publisher!r}"
                if document.publisher
                else "publisher: missing, as you have no organisation to publish for"
            )
        fields = {**document.fields, "publisher_id": publisher}
        return replace(document, fields=fields).with_problems(*problems)

    def _publisher_id(self, wanted: str) -> int | None:
        if not wanted:
            own = self.own_publisher
            return own if own in self.publishers else None
        matches = [
            identifier
            for identifier, name in self.publishers.items()
            if wanted in (name, str(identifier))
        ]
        return matches[0] if len(matches) == 1 else None


def page(item: Any) -> str:
    return item.get("_links", {}).get("page", {}).get("href", "")


def _refused(field: str, value: str, accepted: list[str]) -> str:
    hints = closest(value, accepted)
    hint = f" (closest: {'; '.join(hints)})" if hints else ""
    return f"{field}: {value!r} is not accepted{hint}"
