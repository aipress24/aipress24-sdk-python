# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""``aipress24 post``, against a site in memory."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import PNG, Run, results
from fake_site import URL, FakeSite
from make_archives import make_mastodon, note

from aipress24_client import ApiError
from aipress24_client.cli import post as post_module
from aipress24_client.cli.state import FOLDER


@pytest.fixture(autouse=True)
def fresh_state() -> None:
    """Each command is a new process."""
    post_module._state.cache_clear()


@pytest.fixture
def catalog(tmp_path: Path, run: Run) -> Path:
    archive = make_mastodon(
        tmp_path / "a.zip",
        note("1", "<p>Un</p>", images=[("cover.png", "Alt")]),
        note("2", "<p>Deux</p>"),
        note("3", "<p>@x oui</p>"),
        cover=PNG,
    )
    path = tmp_path / "posts.csv"
    run("catalog", "create", archive, "-o", path)
    return path


def publish(run: Run, catalog: Path, *options: str) -> list[str]:
    post_module._state.cache_clear()
    return results(run("post", "publish", catalog, "--yes", *options)[1])


def test_publish(site: FakeSite, catalog: Path, run: Run) -> None:
    status, lines, err = run("post", "publish", catalog, "--yes")
    assert (status, results(lines)) == (0, ["published", "published"])
    assert "Publish 2 post(s) on https://ex.test, as Pia Ar" in err
    assert lines[0]["page"].startswith(f"{URL}/swork/posts/x")
    first, second = site.wall.values()
    assert first["text"] == "Un"
    assert first["published_at"] == "2024-05-01T10:00:01+00:00"
    assert first["external_ref"] == "https://social.test/@me/1"
    assert first["images"][0]["caption"] == "Alt"
    assert second["images"] == []


def test_publish_again_changes_nothing_and_asks_nothing(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    publish(run, catalog)
    status, lines, _ = run("post", "publish", catalog)
    assert (status, results(lines)) == (0, ["unchanged", "unchanged"])
    # Nor without the cache.
    shutil.rmtree(catalog.parent / FOLDER)
    assert publish(run, catalog) == ["unchanged", "unchanged"]


def test_publish_asks_once(site: FakeSite, catalog: Path, run: Run) -> None:
    status, lines, _ = run("post", "publish", catalog)
    assert (status, lines, site.wall) == (2, [], {})
    assert publish(run, catalog, "--dry-run") == ["new", "new"]
    assert site.wall == {}


def test_what_differs_is_reported(site: FakeSite, catalog: Path, run: Run) -> None:
    publish(run, catalog)
    next(iter(site.wall.values()))["text"] = "Autre"
    status, lines, err = run("post", "publish", catalog)
    assert (status, results(lines)) == (1, ["different", "unchanged"])
    assert "delete it" in err


def test_what_was_deleted_stays_deleted(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    publish(run, catalog)
    site.wall.clear()
    assert publish(run, catalog) == ["deleted", "deleted"]
    assert publish(run, catalog, "--recreate") == ["published", "published"]


def test_a_lost_answer_makes_no_duplicate(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    site.fail["created_post"] = TimeoutError("timed out")
    assert publish(run, catalog) == ["failed", "failed"]
    site.fail.clear()
    assert publish(run, catalog) == ["unchanged", "unchanged"]
    assert len(site.wall) == 2


def test_the_daily_limit_stops_everything(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    site.fail["create_post"] = ApiError(429, {"message": "The limit is 2."})
    status, lines, err = run("post", "publish", catalog, "--yes")
    assert (status, lines) == (1, [])
    assert "again tomorrow" in err
    assert site.calls.count("create_post") == 1
    site.fail.clear()
    assert publish(run, catalog) == ["published", "published"]


def test_a_refused_token_stops_everything(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    site.fail["create_post"] = ApiError(401, None)
    assert run("post", "publish", catalog, "--yes")[:2] == (1, [])
    assert site.calls.count("create_post") == 1


def test_a_failure_does_not_stop_the_others(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    site.fail["create_post"] = ApiError(422, None)
    assert publish(run, catalog) == ["failed", "failed"]


def test_invalid_messages_stop_everything(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    text = catalog.read_text(encoding="utf-8-sig")
    catalog.write_text(text.replace("a.zip#2", "a.zip#9"), encoding="utf-8")
    status, lines, err = run("post", "publish", catalog, "--yes")
    assert (status, results(lines), site.wall) == (1, ["invalid"], {})
    assert "Nothing was sent: 1 of 2" in err
    assert publish(run, catalog, "--skip-invalid") == ["invalid", "published"]


def test_delete_the_posts_of_a_catalog(site: FakeSite, catalog: Path, run: Run) -> None:
    publish(run, catalog)
    assert run("post", "delete", catalog)[0] == 2
    only = ("--only", "*/1", "--yes")
    assert results(run("post", "delete", catalog, *only)[1]) == ["deleted"]
    status, lines, _ = run("post", "delete", catalog, "--yes")
    assert (status, results(lines)) == (0, ["absent", "deleted"])
    assert site.wall == {}


def test_status_list_and_show(site: FakeSite, catalog: Path, run: Run) -> None:
    assert results(run("post", "status", catalog)[1]) == ["new", "new"]
    publish(run, catalog)
    assert results(run("post", "status", catalog)[1]) == ["unchanged"] * 2
    assert results(run("catalog", "status", catalog)[1])[:2] == ["unchanged"] * 2
    first, _ = run("post", "list")[1]
    assert run("post", "show", first["id"])[1] == [first]
    assert run("post", "show", first["page"])[1] == [first]
    assert run("post", "show", "12345")[0] == 1


def test_a_site_without_the_needed_api_is_refused(
    site: FakeSite, catalog: Path, run: Run
) -> None:
    site.fail["posts"] = ApiError(404, None)
    status, _, err = run("post", "publish", catalog, "--yes")
    assert status == 1
    assert "does not offer" in err


def test_check_needs_no_token(
    catalog: Path, run: Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AIPRESS24_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert results(run("post", "check", catalog)[1]) == ["ready", "ready"]
