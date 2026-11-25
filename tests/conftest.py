# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fake_site import URL, FakeSite

from aipress24_client import cli
from aipress24_client.cli.context import Context

PNG = b"\x89PNG\r\n\x1a\n"
SOURCE = """---
title: "Acme lance le Widget"
reference: https://acme.test/news/widget/
published_at: 2014-12-03
summary: Un widget.
genre: Annonce
section: Économie
topic: Innovation
sector: Industrie
images:
  - file: cover.png
    caption: La couverture
---
Un **widget**.

---

Voir [ici](/contact/).
"""


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeSite:
    """The commands talk to this site."""
    fake = FakeSite()
    monkeypatch.setenv("AIPRESS24_TOKEN", "a24_x")
    monkeypatch.setenv("AIPRESS24_SITE", URL)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(Context, "make_client", lambda self, token: fake)
    return fake


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return make_folder(tmp_path / "release")


def make_folder(path: Path, name: str = "") -> Path:
    path.mkdir()
    text = SOURCE.replace("/widget/", f"/widget{name}/")
    (path / "release.md").write_text(text, encoding="utf-8")
    (path / "cover.png").write_bytes(PNG + b"cover")
    return path


def edit(folder: Path, old: str, new: str) -> None:
    path = folder / "release.md"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


Run = Callable[..., tuple[int, list[dict[str, Any]], str]]


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> Run:
    """Run a command, and return its status, its results and its messages."""

    def run(*argv: object) -> tuple[int, list[dict[str, Any]], str]:
        capsys.readouterr()
        status = cli.main([*map(str, argv), "--json"])
        captured = capsys.readouterr()
        return status, list(map(json.loads, captured.out.splitlines())), captured.err

    return run


def results(lines: list[dict[str, Any]]) -> list[str]:
    return [line["result"] for line in lines]
