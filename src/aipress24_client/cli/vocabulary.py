# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Look for values in the vocabularies."""

from __future__ import annotations

import difflib
import unicodedata
from collections.abc import Iterable

_APOSTROPHE = "\N{RIGHT SINGLE QUOTATION MARK}"


def fold(text: str) -> str:
    """Ignore case and accents."""
    decomposed = unicodedata.normalize("NFKD", text.replace(_APOSTROPHE, "'"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def search(text: str, values: Iterable[str]) -> list[str]:
    return [value for value in values if fold(text) in fold(value)]


def closest(text: str, values: Iterable[str]) -> list[str]:
    folded = {fold(value): value for value in values}
    matches = difflib.get_close_matches(fold(text), folded, n=3, cutoff=0.5)
    found = [*(folded[match] for match in matches), *search(text, folded.values())]
    return list(dict.fromkeys(found))[:3]
