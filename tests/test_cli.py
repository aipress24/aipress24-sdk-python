# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the command line, against an in-memory site."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from aipress24_client import ApiError, Client, cli
from aipress24_client.cli.errors import CliError
from aipress24_client.cli.release import load_release
from aipress24_client.cli.state import STATE_FILE
from aipress24_client.cli.sync import check_classification
from aipress24_client.cli.sync import push as sync_push
from aipress24_client.cli.token import find_token

SOURCE = """---
titre: "Acme lance le Widget"
chapo: Un widget.
genre: Annonce
section: Économie
topic: Innovation
sector: Industrie
images:
  - file: cover.jpg
    caption: La couverture
  - other.png
---
Un **widget**.

---

| a | b |
|---|---|
| 1 | 2 |
"""
VOCABULARY = {
    "genre": ["Annonce"],
    "section": ["Économie"],
    "topic": ["Innovation"],
    "sector": ["Industrie"],
}


class FakeSite(Client):
    """A client whose site is kept in memory."""

    def __init__(self, base_url: str = "https://ex.test") -> None:
        super().__init__("a24_x", base_url)
        self.release: dict[str, Any] = {}
        self.images: list[Any] = []
        self.sent: list[str] = []
        self.clock = 0

    def touch(self, **values: Any) -> dict[str, Any]:
        self.clock += 1
        self.release.update(values, modified_at=str(self.clock))
        return dict(self.release)

    def create(self, collection, data):
        return self.touch(id=7, status="draft", **data)

    def update(self, collection, identifier, data):
        return self.touch(**data)

    def publish(self, collection, identifier):
        return self.touch(status="public")

    def get_one(self, collection, identifier):
        if not self.release:
            raise ApiError(404, None)
        return dict(self.release)

    def press_release_vocabularies(self):
        return VOCABULARY

    def press_release_images(self, identifier):
        return list(self.images)

    def add_press_release_image(
        self, identifier, content, filename, caption="", copyright=""
    ):
        self.touch()
        self.sent.append(filename)
        image = {
            "id": self.clock,
            "sha256": hashlib.sha256(content).hexdigest(),
            "caption": caption,
            "copyright": copyright,
        }
        self.images.append(image)
        return image

    def delete_press_release_image(self, identifier, image_id):
        self.touch()
        self.images = [image for image in self.images if image["id"] != image_id]


@pytest.fixture
def site() -> FakeSite:
    return FakeSite()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = tmp_path / "release"
    path.mkdir()
    (path / "release.md").write_text(SOURCE, encoding="utf-8")
    (path / "cover.jpg").write_bytes(b"cover")
    (path / "other.png").write_bytes(b"other")
    return path


def push(site: FakeSite, folder: Path, publish: bool = False, force: bool = False):
    sync_push(site, folder, load_release(folder), publish=publish, force=force)


def edit(folder: Path, old: str, new: str) -> None:
    path = folder / "release.md"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_the_folder_is_read(folder: Path) -> None:
    release = load_release(folder)

    assert release.fields["titre"] == "Acme lance le Widget"
    assert "<strong>widget</strong>" in release.fields["contenu"]
    assert "<hr" in release.fields["contenu"]
    assert "<table>" in release.fields["contenu"]
    assert [image.name for image in release.images] == ["cover.jpg", "other.png"]
    assert release.missing_to_publish() == []


def test_a_push_shows_the_page_of_the_release(
    site: FakeSite, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = "https://ex.test/wip/communiques/7/"
    push(site, folder)
    assert f"Created draft: {url}\n" in capsys.readouterr().out
    push(site, folder)
    assert f"Updated: {url}\n" in capsys.readouterr().out


def test_a_first_push_creates_a_draft(site: FakeSite, folder: Path) -> None:
    push(site, folder)

    assert site.release["status"] == "draft"
    assert site.sent == ["cover.jpg", "other.png"]
    assert site.images[0]["caption"] == "La couverture"
    state = json.loads((folder / STATE_FILE).read_text())
    assert state["id"] == 7


def test_a_second_push_updates_and_resends_no_image(
    site: FakeSite, folder: Path
) -> None:
    push(site, folder)
    edit(folder, "Un widget.", "Deux widgets.")
    push(site, folder, publish=True)

    assert site.release["chapo"] == "Deux widgets."
    assert site.release["status"] == "public"
    assert site.sent == ["cover.jpg", "other.png"]


def test_images_are_replaced_from_the_first_difference(
    site: FakeSite, folder: Path
) -> None:
    push(site, folder)
    (folder / "other.png").write_bytes(b"changed")
    push(site, folder)

    assert site.sent == ["cover.jpg", "other.png", "other.png"]
    assert len(site.images) == 2

    edit(folder, "La couverture", "Autre légende")
    push(site, folder)
    assert site.images[0]["caption"] == "Autre légende"
    assert len(site.images) == 2


def test_a_change_made_on_the_site_is_kept_unless_forced(
    site: FakeSite, folder: Path
) -> None:
    push(site, folder)
    site.touch(titre="Edited on the site")

    with pytest.raises(CliError, match="--force"):
        push(site, folder)
    assert site.release["titre"] == "Edited on the site"

    push(site, folder, force=True)
    assert site.release["titre"] == "Acme lance le Widget"


def test_an_interrupted_push_can_be_run_again(
    site: FakeSite, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any) -> None:
        raise ApiError(413, {"message": "too large"})

    with monkeypatch.context() as patch:
        patch.setattr(site, "add_press_release_image", refuse)
        with pytest.raises(ApiError):
            push(site, folder)
    push(site, folder)

    assert site.release["id"] == 7
    assert len(site.images) == 2


def test_a_folder_stays_bound_to_its_site(site: FakeSite, folder: Path) -> None:
    push(site, folder)
    with pytest.raises(CliError, match="was pushed to"):
        push(FakeSite("https://other.test"), folder)


def test_a_release_deleted_on_the_site_is_not_created_again(
    site: FakeSite, folder: Path
) -> None:
    push(site, folder)
    site.release = {}
    with pytest.raises(CliError, match="not on the site"):
        push(site, folder)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("chapo:", "chapô:", "Unknown front matter: chapô"),
        ("chapo: Un widget.", "chapo: 2026", "chapo: 2026"),
        ("chapo: Un widget.", "publisher_id: true", "publisher_id"),
        ("chapo: Un widget.", "embargoed_until: 2026-12-01", "time zone"),
        ("chapo: Un widget.", "embargoed_until: 2026-12-01T08:00:00", "time zone"),
        ("chapo: Un widget.", "chapo: [", "Invalid front matter"),
        ("Acme lance le Widget", "", "titre"),
        ("other.png", "missing.png", "does not exist"),
        ("other.png", "../secret.png", "outside the folder"),
        ("other.png", "/etc/hosts", "outside the folder"),
        ("other.png", "link.png", "outside the folder"),
        ("Un **widget**.", "![x](other.png)", "list them in images"),
    ],
)
def test_invalid_folders_are_refused(
    folder: Path, old: str, new: str, message: str
) -> None:
    secret = folder.parent / "secret.png"
    secret.write_bytes(b"secret")
    (folder / "link.png").symlink_to(secret)
    edit(folder, old, new)

    with pytest.raises(CliError, match=message):
        load_release(folder)


def test_an_embargo_keeps_its_time_zone(folder: Path) -> None:
    edit(folder, "chapo: Un widget.", "embargoed_until: 2026-12-01T08:00:00+01:00")
    fields = load_release(folder).fields
    assert fields["embargoed_until"] == "2026-12-01T08:00:00+01:00"


def test_raw_html_is_shown_as_text(folder: Path) -> None:
    edit(folder, "Un **widget**.", "<script>x</script>")
    assert "<script>" not in load_release(folder).fields["contenu"]


def test_an_unknown_classification_is_refused(site: FakeSite, folder: Path) -> None:
    edit(folder, "Annonce", "Inconnu")
    with pytest.raises(CliError, match="aipress24 values genre"):
        check_classification(load_release(folder), site)


def test_check_works_without_a_token(
    folder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AIPRESS24_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert cli.main(["check", str(folder)]) == 0
    assert "Ready to publish" in capsys.readouterr().out
    assert cli.main(["push", str(folder)]) == 1
    assert "AIPRESS24_TOKEN" in capsys.readouterr().err


def test_a_token_file_others_can_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIPRESS24_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "aipress24" / "token"
    path.parent.mkdir()
    path.write_text("a24_x\n")

    path.chmod(0o644)
    with pytest.raises(CliError, match="chmod 600"):
        find_token()
    path.chmod(0o600)
    assert find_token() == "a24_x"


@pytest.mark.parametrize(
    "argv",
    [[], ["nope"], ["push"], ["values", "nope"], ["status", "x", "--nope"]],
)
def test_usage(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(argv) == (2 if argv else 0)
    captured = capsys.readouterr()
    assert captured.err if argv else "push" in captured.out


@pytest.mark.parametrize("command", ["check", "push", "status", "values"])
def test_each_command_has_its_help(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([command, "--help"]) == 0
    assert f"aipress24 {command}" in capsys.readouterr().out


@pytest.mark.parametrize("source", ["before", "after", "environment"])
def test_the_site_can_be_chosen(
    source: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AIPRESS24_TOKEN", "a24_x")
    url = "http://127.0.0.1:1"
    argv = ["values", "genre"]
    if source == "before":
        argv = ["--base-url", url, *argv]
    elif source == "after":
        argv = [*argv, "--base-url", url]
    else:
        monkeypatch.setenv("AIPRESS24_URL", url)

    assert cli.main(argv) == 1
    assert f"Cannot reach {url}" in capsys.readouterr().err
