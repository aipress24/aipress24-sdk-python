# Copyright (c) 2025, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""A tiny, dependency-free Python client for the AIpress24 public API.

Uses only the standard library (``urllib``), so it can be vendored or
``pip install``-ed with no transitive dependencies.

    from aipress24_client import Client

    api = Client(token="a24_…", base_url="https://aipress24.com")
    for article in api.iter("articles"):
        print(article["title"], article["_links"]["self"]["href"])

Every resource is exposed generically via :meth:`Client.list`,
:meth:`Client.get_one` and :meth:`Client.iter`, plus named convenience
methods (``articles``, ``events``, ``members``, …).
"""

from __future__ import annotations

from ._generated import (
    COLLECTIONS,
    Article,
    BusinessWall,
    Event,
    Member,
    Organisation,
    PressRelease,
    PressReleaseImage,
    PressReleaseVocabularies,
    SelfProfile,
)
from .client import DEFAULT_BASE_URL, ApiError, Client, Page

__all__ = [
    "COLLECTIONS",
    "DEFAULT_BASE_URL",
    "ApiError",
    "Article",
    "BusinessWall",
    "Client",
    "Event",
    "Member",
    "Organisation",
    "Page",
    "PressRelease",
    "PressReleaseImage",
    "PressReleaseVocabularies",
    "SelfProfile",
]

__version__ = "0.1.0"
