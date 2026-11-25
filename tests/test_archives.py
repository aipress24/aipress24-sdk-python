# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Reading the archives of social networks."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from conftest import PNG, Run, results
from make_archives import (
    ACTOR,
    DID,
    encode,
    facet,
    make_car,
    make_mastodon,
    note,
    post,
    reply_to,
    uri,
)

from aipress24_client.cli.archives import read_archive
from aipress24_client.cli.archives.car import decode
from aipress24_client.cli.archives.mastodon import text_of
from aipress24_client.cli.errors import CliError

FOLLOWERS = {"to": [f"{ACTOR}/followers"], "cc": []}
DIRECT = {"to": ["https://other.test/users/you"], "cc": []}
UNLISTED = {
    "to": [f"{ACTOR}/followers"],
    "cc": ["https://www.w3.org/ns/activitystreams#Public"],
}
OTHER = "https://other.test/statuses/1"
LONG = "Un message assez long pour être reconnu sur plusieurs réseaux"


def reasons(path: Path) -> dict[str, str]:
    return {key: each.reason for key, each in read_archive(path).messages.items()}


# --- Mastodon --------------------------------------------------------------


def test_mastodon_threads_and_replies(tmp_path: Path) -> None:
    path = make_mastodon(
        tmp_path / "a.zip",
        note("1", "<p>Un</p>"),
        note("2", "<p>Deux</p>", reply="1"),
        note("3", "<p>Trois</p>", reply="2"),
        note("4", "<p>@x oui</p>", reply=OTHER),
        note("5", "<p>et encore</p>", reply="4"),
        note("6", "<p>@x parent perdu</p>"),
        note("7", "<p>Discret</p>", **UNLISTED),
        note("8", "<p>Suite</p>", reply="7"),
    )
    assert reasons(path) == {
        "1": "",
        "4": "reply",
        "5": "in the thread of someone else",
        "6": "reply to a deleted message",
        "7": "unlisted",
        "8": "unlisted",
    }
    message = read_archive(path).messages["1"]
    assert message.text == "Un\n\nDeux\n\nTrois"
    assert message.url == "https://social.test/@me/1"
    assert message.published.isoformat() == "2024-05-01T10:00:01+00:00"


def test_mastodon_private_messages_and_boosts_are_never_read(tmp_path: Path) -> None:
    path = make_mastodon(
        tmp_path / "a.zip",
        note("1", "<p>Public</p>"),
        note("2", "<p>secret</p>", **FOLLOWERS),
        note("3", "<p>secret</p>", **DIRECT),
        {"type": "Announce", "object": OTHER},
    )
    archive = read_archive(path)
    assert list(archive.messages) == ["1"]
    assert archive.ignored == {"private": 2, "boost": 1}


def test_mastodon_a_private_answer_is_not_in_the_thread(tmp_path: Path) -> None:
    path = make_mastodon(
        tmp_path / "a.zip",
        note("1", "<p>Un</p>"),
        note("2", "<p>secret</p>", reply="1", **FOLLOWERS),
    )
    assert read_archive(path).messages["1"].text == "Un"


def test_mastodon_a_loop_is_survived(tmp_path: Path) -> None:
    path = make_mastodon(
        tmp_path / "a.zip", note("1", "a", reply="2"), note("2", "b", reply="1")
    )
    assert len(read_archive(path).messages) == 2


def test_mastodon_text() -> None:
    html = (
        '<p>Voir <a href="https://x.test/a/long/path?b=1&amp;c=2">'
        '<span class="invisible">https://</span><span class="ellipsis">x.test/a</span>'
        "</a><br />R&amp;D</p>"
        '<p><span class="h-card"><a href="https://mamot.fr/@you" class="u-url mention">'
        "@<span>you</span></a></span> "
        '<a href="https://social.test/tags/foss" class="mention hashtag">'
        "#<span>foss</span></a></p>"
    )
    assert text_of(html) == (
        "Voir https://x.test/a/long/path?b=1&c=2\nR&D\n\n@you@mamot.fr #foss"
    )


def test_mastodon_images(tmp_path: Path) -> None:
    path = make_mastodon(
        tmp_path / "a.zip",
        note("1", "<p>Un</p>", images=[("cover.png", "Une image")]),
        note("2", "<p>Deux</p>", reply="1", images=[("absent.png", None)]),
        cover=PNG,
    )
    first, second = read_archive(path).messages["1"].images
    assert (first.name, first.caption, first.content) == ("cover.png", "Une image", PNG)
    assert (second.caption, second.content) == ("", None)


# --- Bluesky ---------------------------------------------------------------


def test_bluesky_threads_and_replies(tmp_path: Path) -> None:
    other = "at://did:plc:other/app.bsky.feed.post/z"
    path = make_car(
        tmp_path / "repo.car",
        {
            "a": post("Un", second=1),
            "b": post("Deux", second=2, reply=reply_to(uri("a"))),
            "c": post("oui", second=3, reply=reply_to(other)),
            "d": post("encore", second=4, reply=reply_to(uri("c"))),
        },
        **{"app.bsky.feed.repost/r": {"subject": {"uri": other}}},
        **{"app.bsky.graph.block/b": {"subject": "did:plc:other"}},
    )
    assert reasons(path) == {
        "a": "",
        "c": "reply",
        "d": "in the thread of someone else",
    }
    archive = read_archive(path)
    assert archive.messages["a"].text == "Un\n\nDeux"
    assert archive.messages["a"].url == f"https://bsky.app/profile/{DID}/post/a"
    assert archive.ignored == {"repost": 1}


def test_bluesky_text(tmp_path: Path) -> None:
    text = "Été: x.test/lo... et y.test"
    link = "app.bsky.richtext.facet#link"
    facets = [
        facet(text, "x.test/lo...", **{"$type": link, "uri": "https://x.test/long"}),
        facet(text, "y.test", **{"$type": link, "uri": "https://y.test/"}),
    ]
    card = {"uri": "https://z.test/", "title": "Titre", "description": ""}
    external = {"$type": "app.bsky.embed.external", "external": card}
    images = {
        "$type": "app.bsky.embed.images",
        "images": [{"alt": "Alt", "image": {"ref": b"x", "size": 9}}],
    }
    path = make_car(
        tmp_path / "repo.car",
        {
            "a": post(text, facets=facets),
            "b": post("Lire", embed=external),
            "c": post("", embed=external),
            "d": post("Vu", embed=images),
        },
    )
    messages = read_archive(path).messages
    assert messages["a"].text == "Été: https://x.test/long et https://y.test/"
    assert messages["b"].text == "Lire\n\nhttps://z.test/"
    assert messages["c"].text == "Titre\n\nhttps://z.test/"
    (image,) = messages["d"].images
    assert (image.caption, image.content) == ("Alt", None)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        23,
        24,
        255,
        70000,
        2**40,
        -1,
        -500,
        "é" * 300,
        b"x",
        [],
        {},
    ],
)
def test_cbor(value: object) -> None:
    data = encode({"v": value, "w": [value]})
    assert decode(data) == ({"v": value, "w": [value]}, len(data))


# --- damaged archives ------------------------------------------------------


def test_damaged_archives_are_refused(tmp_path: Path) -> None:
    good = make_car(tmp_path / "repo.car", {"a": post("Un"), "b": post("Deux")})
    data = good.read_bytes()
    for name, content in (
        ("short.car", data[:-20]),
        ("changed.car", data[:-1] + b"\x00"),
        ("empty.car", b""),
        ("nested.car", b"\x81" * 100_000),
        ("text.zip", b"text"),
    ):
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(CliError):
            read_archive(path)


# --- catalogs --------------------------------------------------------------


def rows(catalog: Path) -> dict[str, dict[str, str]]:
    with catalog.open(encoding="utf-8-sig", newline="") as file:
        return {row["source"]: row for row in csv.DictReader(file)}


def test_a_catalog_of_both_networks(tmp_path: Path, run: Run) -> None:
    mastodon = make_mastodon(
        tmp_path / "m.zip",
        note("1", f"<p>{LONG}</p>", images=[("cover.png", "")]),
        note("2", "<p>@x oui</p>", reply=OTHER),
        note("3", "<p>Court</p>"),
        cover=PNG,
    )
    bluesky = make_car(
        tmp_path / "b.car",
        {"a": post(f"{LONG} !"), "b": post("Court"), "c": post("@x.test")},
    )
    catalog = tmp_path / "posts.csv"
    status, _, err = run("catalog", "create", mastodon, bluesky, "-o", catalog)
    assert status == 0
    assert "1 same as" in err

    found = rows(catalog)
    kept = [source for source, row in found.items() if row["type"] == "post"]
    assert kept == ["m.zip#1", "m.zip#3", "b.car#b"]
    assert found["b.car#a"]["note"] == "same as https://social.test/@me/1"
    assert found["m.zip#2"]["note"] == "reply"
    assert "mentions aside" in found["b.car#c"]["note"]

    status, lines, _ = run("post", "check", catalog)
    assert (status, results(lines)) == (0, ["ready"] * 3)
    assert lines[0]["reference"] == "https://social.test/@me/1"


def test_a_newer_archive_only_adds_what_is_new(tmp_path: Path, run: Run) -> None:
    old = make_mastodon(tmp_path / "old.zip", note("1", f"<p>{LONG}</p>"))
    catalog = tmp_path / "posts.csv"
    run("catalog", "create", old, "-o", catalog)
    new = make_mastodon(
        tmp_path / "new.zip", note("1", f"<p>{LONG}</p>"), note("2", "<p>Deux</p>")
    )
    bluesky = make_car(tmp_path / "b.car", {"a": post(LONG)})
    run("catalog", "update", catalog, new, bluesky)
    found = rows(catalog)
    assert list(found) == ["old.zip#1", "new.zip#2", "b.car#a"]
    assert found["b.car#a"]["type"] == "skip"


def test_what_is_private_cannot_be_asked_for(tmp_path: Path, run: Run) -> None:
    make_mastodon(tmp_path / "a.zip", note("1", "secret", **DIRECT))
    catalog = tmp_path / "posts.csv"
    catalog.write_text("source,type\na.zip#1,post\n")
    status, (line,), _ = run("post", "check", catalog)
    assert status == 1
    assert line["problems"] == ["not in the archive, or not public"]
    assert "secret" not in str(line)


def test_check_reports_problems(tmp_path: Path, run: Run) -> None:
    make_mastodon(
        tmp_path / "a.zip",
        note("1", "<p>Un</p>", images=[("absent.png", "")]),
        note("2", "<p>@x</p>"),
        note("3", "<p>Trois</p>"),
    )
    catalog = tmp_path / "posts.csv"
    catalog.write_text(
        "source,type,published_at\na.zip#1,post,\na.zip#2,post,\na.zip#3,post,1999-01-01\n"
    )
    status, lines, _ = run("post", "check", catalog)
    assert status == 1
    assert results(lines) == ["ready", "invalid", "invalid"]
    assert "not in the archive" in lines[0]["warnings"][0]
    assert "before 2000" in lines[2]["problems"][0]
