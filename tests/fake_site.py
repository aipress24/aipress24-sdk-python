# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""A site kept in memory."""

from __future__ import annotations

import hashlib
from typing import Any

from aipress24_client import ApiError, Client

URL = "https://ex.test"
OWN = 1
VOCABULARIES = {
    "genre": ["Annonce"],
    "section": ["Économie", "Numérique / Cloud"],
    "topic": ["Innovation"],
    "sector": ["Industrie"],
}
DEFAULTS = {
    "status": "draft",
    "published_at": None,
    "publisher_id": None,
    "external_ref": None,
    "genre": "",
    "section": "",
    "topic": "",
    "sector": "",
}


class FakeSite(Client):
    """A client which is its own site. ``fail`` maps a method to an error."""

    def __init__(self) -> None:
        super().__init__("a24_x", URL)
        self.releases: dict[int, dict[str, Any]] = {}
        self.carousels: dict[int, list[Any]] = {}
        self.organisation_id: int | None = OWN
        self.allowed = [{"id": OWN, "name": "Acme"}, {"id": 2, "name": "Client"}]
        self.fail: dict[str, Exception] = {}
        self.calls: list[str] = []
        self.wall: dict[int, dict[str, Any]] = {}
        self.next_id = 100

    def called(self, method: str) -> None:
        self.calls.append(method)
        if method in self.fail:
            raise self.fail[method]

    # --- what the site does -----------------------------------------------

    def only(self) -> dict[str, Any]:
        (release,) = self.releases.values()
        return release

    def get(self, identifier: int) -> dict[str, Any]:
        if identifier not in self.releases:
            raise ApiError(404, None)
        return self.releases[identifier]

    # --- the client's methods ---------------------------------------------

    def me(self):
        return {
            "full_name": "Pia Ar",
            "organisation_id": self.organisation_id,
            "organisation_name": "Acme" if self.organisation_id else "",
        }

    def publishers(self):
        self.called("publishers")
        return self.allowed

    def press_release_vocabularies(self):
        return VOCABULARIES

    def iter(self, collection, limit=50):
        if collection == "me/posts":
            self.called("posts")
            return iter(list(self.wall.values()))
        return iter([self.show(each) for each in self.releases])

    def get_one(self, collection, identifier):
        self.get(identifier)
        return self.show(identifier)

    def show(self, identifier: int) -> dict[str, Any]:
        release = self.get(identifier)
        place = "wire" if release["status"] == "public" else "wip/communiques"
        link = {"page": {"href": f"/{place}/x{identifier}/"}}
        return {**release, "_links": link}

    def create(self, collection, data):
        self.called("create")
        if any(
            r["external_ref"] == data["external_ref"] for r in self.releases.values()
        ):
            raise ApiError(409, {"message": "already used"})
        self.next_id += 1
        self.releases[self.next_id] = {**DEFAULTS, "id": self.next_id, **stored(data)}
        self.carousels[self.next_id] = []
        self.called("created")
        return self.show(self.next_id)

    def update(self, collection, identifier, data):
        self.called("update")
        self.get(identifier).update(stored(data))
        return self.show(identifier)

    def publish(self, collection, identifier):
        self.called("publish")
        release = self.get(identifier)
        release["status"] = "public"
        release["published_at"] = release["published_at"] or "2026-11-25T10:00:00+00:00"
        return self.show(identifier)

    def unpublish(self, collection, identifier):
        self.called("unpublish")
        self.get(identifier)["status"] = "draft"
        return self.show(identifier)

    def delete(self, collection, identifier):
        self.called("delete")
        del (self.wall if collection == "me/posts" else self.releases)[identifier]

    def create_post(self, text, *, published_at=None, external_ref=None, images=()):
        self.called("create_post")
        if any(post["external_ref"] == external_ref for post in self.wall.values()):
            raise ApiError(409, {"message": "already used"})
        self.next_id += 1
        self.wall[self.next_id] = {
            "id": self.next_id,
            "text": text.strip(),
            "published_at": published_at,
            "external_ref": external_ref,
            "like_count": 0,
            "images": [
                {"sha256": hashlib.sha256(content).hexdigest(), "caption": caption}
                for _, content, caption in images
            ],
            "_links": {"page": {"href": f"/swork/posts/x{self.next_id}"}},
        }
        self.called("created_post")
        return self.wall[self.next_id]

    def press_release_images(self, identifier):
        self.get(identifier)
        return list(self.carousels[identifier])

    def add_press_release_image(
        self, identifier, content, filename, caption="", copyright=""
    ):
        self.called("add_image")
        image = {
            "id": len(self.calls),
            "sha256": hashlib.sha256(content).hexdigest(),
            "caption": caption,
            "copyright": copyright,
        }
        self.carousels[identifier].append(image)
        return image

    def delete_press_release_image(self, identifier, image_id):
        self.called("delete_image")
        self.carousels[identifier] = [
            image for image in self.carousels[identifier] if image["id"] != image_id
        ]


def stored(data: dict[str, Any]) -> dict[str, Any]:
    """As the site does, rewrite what it is given."""
    changes = dict(data)
    if "contenu" in changes:
        changes["contenu"] = changes["contenu"].replace("<hr/>", "<hr>")
    return changes
