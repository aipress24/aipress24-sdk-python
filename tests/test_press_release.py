# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""``aipress24 press-release``, against a site in memory."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import PNG, Run, edit, make_folder, results
from fake_site import OWN, URL, FakeSite

from aipress24_client import ApiError
from aipress24_client.cli.state import FOLDER


def draft(run: Run, folder: Path, *options: str) -> str:
    _, (line,), _ = run("press-release", "draft", folder, *options)
    return line["result"]


def publish(run: Run, folder: Path, *options: str) -> str:
    _, (line,), _ = run("press-release", "publish", folder, "--yes", *options)
    return line["result"]


# --- draft -----------------------------------------------------------------


def test_draft_creates_then_updates(site: FakeSite, folder: Path, run: Run) -> None:
    status, (line,), _ = run("press-release", "draft", folder)
    assert (status, line["result"], line["status"]) == (0, "created", "draft")
    assert line["page"] == f"{URL}/wip/communiques/x{line['id']}/"
    release = site.only()
    assert release["publisher_id"] == OWN
    assert release["published_at"] == "2014-12-03T06:00:00+01:00"

    assert draft(run, folder) == "unchanged"
    edit(folder, "Un widget.", "Deux widgets.")
    assert draft(run, folder) == "updated"
    assert site.only()["chapo"] == "Deux widgets."
    assert site.calls.count("add_image") == 1


def test_images_are_replaced_from_the_first_difference(
    site: FakeSite, folder: Path, run: Run
) -> None:
    edit(folder, "    caption: La couverture", "  - other.png")
    (folder / "other.png").write_bytes(PNG + b"other")
    draft(run, folder)
    (folder / "other.png").write_bytes(PNG + b"changed")
    assert draft(run, folder) == "updated"
    assert site.calls.count("add_image") == 3
    (carousel,) = site.carousels.values()
    assert len(carousel) == 2


def test_draft_leaves_a_public_text_alone(
    site: FakeSite, folder: Path, run: Run
) -> None:
    publish(run, folder)
    assert run("press-release", "draft", folder)[0] == 0
    edit(folder, "Un widget.", "Deux widgets.")
    status, (line,), _ = run("press-release", "draft", folder)
    assert (status, line["result"]) == (1, "public")
    assert site.only()["chapo"] == "Un widget."


def test_nothing_is_sent_when_a_document_is_invalid(
    site: FakeSite, folder: Path, run: Run, tmp_path: Path
) -> None:
    other = make_folder(tmp_path / "other", "2")
    edit(other, "Annonce", "Inconnu")
    status, lines, err = run("press-release", "draft", folder, other)
    assert status == 1
    assert "Nothing was sent: 1 of 2" in err
    assert results(lines) == ["invalid"]
    assert site.releases == {}

    status, lines, _ = run("press-release", "draft", folder, other, "--skip-invalid")
    assert status == 1
    assert results(lines) == ["invalid", "created"]


def test_dry_run_sends_nothing(site: FakeSite, folder: Path, run: Run) -> None:
    assert draft(run, folder, "--dry-run") == "new"
    assert publish(run, folder, "--dry-run") == "new"
    assert site.releases == {}


# --- both sides ------------------------------------------------------------


def test_a_change_on_the_site_is_kept(site: FakeSite, folder: Path, run: Run) -> None:
    draft(run, folder)
    site.only()["titre"] = "Corrigé"
    assert draft(run, folder) == "kept"
    assert publish(run, folder) == "published"
    assert site.only()["titre"] == "Corrigé"
    assert publish(run, folder) == "kept"


def test_a_change_on_both_sides_is_a_conflict(
    site: FakeSite, folder: Path, run: Run
) -> None:
    draft(run, folder)
    site.only()["titre"] = "Corrigé"
    edit(folder, "Un widget.", "Deux widgets.")
    status, (line,), err = run("press-release", "draft", folder)
    assert (status, line["result"]) == (1, "conflict")
    assert "here: chapo; on the site: titre" in line["problems"][0]
    assert "--overwrite" in err
    assert draft(run, folder, "--overwrite") == "updated"
    assert site.only()["titre"] == "Acme lance le Widget"


def test_a_change_of_images_on_the_site_counts(
    site: FakeSite, folder: Path, run: Run
) -> None:
    draft(run, folder)
    site.carousels[site.only()["id"]].clear()
    assert draft(run, folder) == "kept"


def test_what_was_deleted_stays_deleted(site: FakeSite, folder: Path, run: Run) -> None:
    draft(run, folder)
    site.releases.clear()
    status, (line,), err = run("press-release", "publish", folder, "--yes")
    assert (status, line["result"]) == (1, "deleted")
    assert "--recreate" in err
    assert publish(run, folder, "--recreate") == "published"


def test_without_the_cache_the_reference_prevents_a_duplicate(
    site: FakeSite, folder: Path, run: Run
) -> None:
    draft(run, folder)
    shutil.rmtree(folder / FOLDER)
    assert draft(run, folder) == "conflict"
    assert draft(run, folder, "--overwrite") == "updated"
    assert len(site.releases) == 1

    publish(run, folder)
    shutil.rmtree(folder / FOLDER)
    assert draft(run, folder) == "conflict"
    assert draft(run, folder, "--overwrite") == "public"


# --- failures --------------------------------------------------------------


def test_a_creation_whose_answer_was_lost_is_found_again(
    site: FakeSite, folder: Path, run: Run
) -> None:
    site.fail["created"] = TimeoutError("timed out")
    assert draft(run, folder) == "failed"
    assert len(site.releases) == 1
    site.fail.clear()
    assert draft(run, folder) == "updated"
    assert len(site.releases) == 1
    assert draft(run, folder) == "unchanged"


def test_an_interrupted_sending_is_completed(
    site: FakeSite, folder: Path, run: Run
) -> None:
    site.fail["add_image"] = ApiError(413, {"message": "too large"})
    assert draft(run, folder) == "failed"
    site.fail.clear()
    assert draft(run, folder) == "updated"
    (carousel,) = site.carousels.values()
    assert len(carousel) == 1


def test_a_failed_publication_is_run_again(
    site: FakeSite, folder: Path, run: Run
) -> None:
    site.fail["publish"] = ApiError(500, None)
    assert publish(run, folder) == "failed"
    site.fail.clear()
    assert publish(run, folder) == "published"
    assert site.calls.count("create") == 1


def test_a_failure_does_not_stop_the_others(
    site: FakeSite, folder: Path, run: Run, tmp_path: Path
) -> None:
    other = make_folder(tmp_path / "other", "2")
    site.fail["add_image"] = ApiError(413, None)
    status, lines, err = run("press-release", "draft", folder, other)
    assert status == 1
    assert results(lines) == ["failed", "failed"]
    assert "Run the same command again" in err


def test_a_refused_token_stops_everything(
    site: FakeSite, folder: Path, run: Run, tmp_path: Path
) -> None:
    other = make_folder(tmp_path / "other", "2")
    site.fail["create"] = ApiError(401, None)
    status, lines, err = run("press-release", "draft", folder, other)
    assert (status, lines) == (1, [])
    assert "refused the token" in err
    assert site.calls.count("create") == 1


def test_a_site_without_the_needed_api_is_refused(
    site: FakeSite, folder: Path, run: Run
) -> None:
    site.fail["publishers"] = ApiError(404, None)
    status, _, err = run("press-release", "draft", folder)
    assert status == 1
    assert "does not offer" in err


# --- publish ---------------------------------------------------------------


def test_publish_asks_once_for_the_batch(
    site: FakeSite, folder: Path, run: Run, tmp_path: Path
) -> None:
    other = make_folder(tmp_path / "other", "2")
    edit(other, "published_at: 2014-12-03", "published_at: 2025-09-26")
    status, lines, err = run("press-release", "publish", folder, other)
    assert (status, lines) == (2, [])
    assert "Publish 2 press release(s) on https://ex.test, for Acme" in err
    assert "from 2014-12-03 to 2025-09-26" in err
    assert site.releases == {}

    status, lines, _ = run("press-release", "publish", folder, other, "--yes")
    assert (status, results(lines)) == (0, ["published", "published"])
    assert lines[0]["page"].startswith(f"{URL}/wire/")


def test_publish_again_changes_nothing_and_asks_nothing(
    site: FakeSite, folder: Path, run: Run
) -> None:
    publish(run, folder)
    status, lines, _ = run("press-release", "publish", folder)
    assert (status, results(lines)) == (0, ["unchanged"])


def test_publish_updates_a_public_text(site: FakeSite, folder: Path, run: Run) -> None:
    publish(run, folder)
    edit(folder, "Un widget.", "Deux widgets.")
    assert run("press-release", "publish", folder)[0] == 2
    assert publish(run, folder) == "updated"
    assert site.only()["chapo"] == "Deux widgets."


def test_publish_needs_a_classification(site: FakeSite, folder: Path, run: Run) -> None:
    edit(folder, "genre: Annonce\n", "")
    status, (line,), _ = run("press-release", "publish", folder, "--yes")
    assert status == 1
    assert line["problems"] == ["missing to publish: genre"]
    # It can also be given on the site.
    draft(run, folder)
    site.only()["genre"] = "Annonce"
    assert publish(run, folder) == "published"


def test_an_embargo_prevents_publishing(site: FakeSite, folder: Path, run: Run) -> None:
    edit(folder, "genre:", "embargoed_until: 2999-01-01T08:00:00+01:00\ngenre:")
    assert draft(run, folder) == "created"
    _, (line,), _ = run("press-release", "publish", folder, "--yes")
    assert "under embargo" in line["problems"][0]


def test_publish_an_item_sends_nothing(site: FakeSite, folder: Path, run: Run) -> None:
    draft(run, folder)
    edit(folder, "Un widget.", "Deux widgets.")
    identifier = site.only()["id"]
    status, (line,), _ = run("press-release", "publish", identifier, "--yes")
    assert (status, line["result"]) == (0, "published")
    assert site.only()["chapo"] == "Un widget."


# --- publisher -------------------------------------------------------------


def test_the_publisher_is_a_name_or_an_id(
    site: FakeSite, folder: Path, run: Run
) -> None:
    edit(folder, "genre:", "publisher: Client\ngenre:")
    draft(run, folder)
    assert site.only()["publisher_id"] == 2
    edit(folder, "publisher: Client", "publisher: 1")
    draft(run, folder)
    assert site.only()["publisher_id"] == 1


def test_a_publisher_is_needed(site: FakeSite, folder: Path, run: Run) -> None:
    site.organisation_id = None
    _, (line,), _ = run("press-release", "draft", folder)
    assert "publisher: missing" in line["problems"][0]
    edit(folder, "genre:", "publisher: Inconnu\ngenre:")
    _, (line,), _ = run("press-release", "draft", folder)
    assert "'Inconnu'" in line["problems"][0]


# --- unpublish, delete, list, show -----------------------------------------


def test_unpublish_then_delete(site: FakeSite, folder: Path, run: Run) -> None:
    publish(run, folder)
    page = run("press-release", "show", folder)[1][0]["page"]
    assert run("press-release", "unpublish", page)[0] == 2
    assert results(run("press-release", "unpublish", page, "--yes")[1]) == ["draft"]
    assert site.only()["status"] == "draft"
    assert results(run("press-release", "unpublish", folder)[1]) == ["unchanged"]

    assert results(run("press-release", "delete", folder, "--yes")[1]) == ["deleted"]
    assert site.releases == {}
    assert results(run("press-release", "delete", folder, "--yes")[1]) == ["absent"]
    assert draft(run, folder) == "deleted"


def test_an_unknown_item_is_refused(site: FakeSite, run: Run) -> None:
    assert run("press-release", "show", "12345")[0] == 1
    assert run("press-release", "show", f"{URL}/wire/xZ/")[0] == 1
    assert run("press-release", "show", "https://other.test/wire/xZ/")[0] == 2


def test_documents_and_items_do_not_mix(site: FakeSite, folder: Path, run: Run) -> None:
    assert run("press-release", "publish", folder, "12", "--yes")[0] == 2
    assert run("press-release", "draft", "12")[0] == 2


def test_list_and_show(site: FakeSite, folder: Path, run: Run) -> None:
    draft(run, folder)
    (listed,) = run("press-release", "list")[1]
    (shown,) = run("press-release", "show", listed["id"])[1]
    assert listed == shown
    assert shown["title"] == "Acme lance le Widget"


# --- check, status ---------------------------------------------------------


def test_check(site: FakeSite, folder: Path, run: Run) -> None:
    status, (line,), _ = run("press-release", "check", folder)
    assert (status, line["result"]) == (0, "ready")
    edit(folder, "genre: Annonce\n", "")
    assert results(run("press-release", "check", folder)[1]) == ["draft-only"]
    edit(folder, "section: Économie", "section: numerique")
    status, (line,), _ = run("press-release", "check", folder)
    assert (status, line["result"]) == (1, "invalid")
    assert "closest: Numérique / Cloud" in line["problems"][0]


def test_check_works_without_a_token(
    folder: Path, run: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIPRESS24_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    status, lines, err = run("press-release", "check", folder)
    assert (status, results(lines)) == (0, ["ready"])
    assert "No token" in err
    assert run("press-release", "draft", folder)[0] == 1


def test_status(site: FakeSite, folder: Path, run: Run) -> None:
    def state() -> str:
        return results(run("press-release", "status", folder)[1])[0]

    assert state() == "new"
    draft(run, folder)
    assert state() == "unchanged"
    edit(folder, "Un widget.", "Deux widgets.")
    assert state() == "changed"
    site.only()["titre"] = "Corrigé"
    assert state() == "conflict"
    site.releases.clear()
    assert state() == "deleted"
