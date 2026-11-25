# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
#
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts>=5.5,<6", "pyyaml>=6"]
# ///
"""Convert the press releases of abilian.com into ``aipress24 push`` folders.

    uv run examples/abilian_news.py ../../web/abilian.com ../abilian-releases

Running it again rewrites the texts and images, and keeps ``.aipress24.json``.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cyclopts
import yaml

SITE = "https://abilian.com"
DEFAULT_ILLUSTRATION = "abilian.png"
MONTHS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


@dataclass(frozen=True)
class Classification:
    """What AIpress24 needs to publish, and the news don't say."""

    genre: str
    section: str
    topic: str
    sector: str = "Numérique / Cloud, logiciels & open source"


# The news that are press releases: the company announces something of its own,
# or takes a position, in a text meant for others to quote.
RELEASES = {
    "deux-financements-europeens-pour-hop3": Classification(
        "Business / Financement, levée de fonds",
        "Numérique / Innovation technologique",
        "Numérique, internet / Cloud",
    ),
    "feuille-de-route-europeenne-sur-la-souverainete-numerique": Classification(
        "Document source / Rapport",
        "International / Union européenne",
        "Numérique, internet / Souveraineté numérique",
    ),
    "souverainete-numerique-sondage-grand-continent": Classification(
        "Prise de parole / Prise de position",
        "International / Union européenne",
        "Numérique, internet / Souveraineté numérique",
    ),
    "lettre-ouverte-eurostack": Classification(
        "Prise de parole / Prise de position",
        "International / Union européenne",
        "Numérique, internet / Souveraineté numérique",
    ),
    "publication-du-guide-du-logiciel-libre-pour-les-pme": Classification(
        "Document source / Recommandations, guide",
        "Entreprise / PME, TPE",
        "Numérique, internet / Logiciel libre",
    ),
    "abilian-cybersecurite-chartecyber": Classification(
        "Engagement / Engagement RSE",
        "Numérique / Cybersécurité",
        "Numérique, internet / Cybersécurité",
        "Numérique / Cybersécurité",
    ),
    "coalition-for-competitive-digital-markets": Classification(
        "Prise de parole / Prise de position",
        "International / Union européenne",
        "Numérique, internet / Plateformes numériques",
    ),
    "euclidia-alliance-europeenne-industriels-cloud": Classification(
        "Business / Partenariat",
        "International / Union européenne",
        "Numérique, internet / Cloud",
    ),
    "wendelin-projet-big-data": Classification(
        "Business / Financement, levée de fonds",
        "Numérique / Innovation technologique",
        "Sciences, recherche / Recherche scientifique",
        "Numérique / Intelligence artificielle & données",
    ),
    "commercialisation-abilian-sics-pc": Classification(
        "Offre, marque / Lancement de produit",
        "Numérique / Logiciels",
        "Numérique, internet / Logiciel libre",
    ),
}

_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_HTML = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
_AUTOLINK = re.compile(r"<(https?://|mailto:)")


def main(site: Path, output: Path, /) -> None:
    """Convert the press releases.

    Parameters
    ----------
    site
        The Lektor project of abilian.com.
    output
        Where to write one folder per press release.
    """
    for slug, classification in RELEASES.items():
        convert(site, slug, classification, output / slug)
        print(output / slug)


def convert(
    site: Path, slug: str, classification: Classification, folder: Path
) -> None:
    source = site / "content" / "fr" / "news" / slug
    news = parse_lektor((source / "contents.lr").read_text(encoding="utf-8"))
    body, captions = extract_images(news["body"])
    illustration = news.get("illustration", DEFAULT_ILLUSTRATION)
    images = {f"/static/illustrations/{illustration}": "", **captions}

    folder.mkdir(parents=True, exist_ok=True)
    matter = {
        "titre": re.sub(r"^\[[^\]]*\]\s*", "", news["title"]),
        "chapo": plain_text(news["description"]),
        **vars(classification),
        "language": "fr",
        "pays_zip_ville": "FRA",
        "images": [
            copy_image(site, source, url, folder) | ({"caption": text} if text else {})
            for url, text in images.items()
        ],
    }
    header = yaml.safe_dump(matter, allow_unicode=True, sort_keys=False, width=10**6)
    note = origin(date.fromisoformat(news["pub_date"]), slug)
    (folder / "release.md").write_text(
        f"---\n{header}---\n\n{note}\n\n{clean_markdown(body)}\n", encoding="utf-8"
    )


def parse_lektor(text: str) -> dict[str, str]:
    """Read the fields of a ``contents.lr``: they are separated by ``---``."""
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.strip() == "---":
            blocks.append([])
        else:
            # Lektor escapes a line of dashes in a field with one more dash.
            blocks[-1].append(line[1:] if re.fullmatch(r"-{4,}\s*", line) else line)
    fields = {}
    for block in blocks:
        key, _, value = "\n".join(block).strip().partition(":")
        fields[key] = value.strip()
    return fields


def extract_images(body: str) -> tuple[str, dict[str, str]]:
    """Take the images out of the text, as ``{url: caption}``."""
    images = {url: text for text, url in _IMAGE.findall(body)}
    return _IMAGE.sub("", body), images


def clean_markdown(body: str) -> str:
    body = body.replace("￼", "")  # left by a copy and paste
    body = re.sub(r"<br\s*/?>", "", body)
    # Blank lines around, as a line before it would become a title.
    body = re.sub(r"<hr\s*/?>", "\n\n---\n\n", body)
    if html := _HTML.findall(_AUTOLINK.sub("", body)):
        msg = f"HTML which is not converted: {html}"
        raise ValueError(msg)
    body = re.sub(r"\]\(/", f"]({SITE}/", body)
    return re.sub(r"\n\s*\n+", "\n\n", body).strip()


def plain_text(text: str) -> str:
    return " ".join(text.replace("*", "").split())


def origin(published: date, slug: str) -> str:
    """Tell the reader the date of the release, which AIpress24 cannot hold."""
    day = "1er" if published.day == 1 else published.day
    when = f"{day} {MONTHS[published.month - 1]} {published.year}"
    return f"*Communiqué [publié le {when}]({SITE}/fr/news/{slug}/) par Abilian.*"


def copy_image(site: Path, source: Path, url: str, folder: Path) -> dict[str, str]:
    path = site / "assets" / url.lstrip("/") if url.startswith("/") else source / url
    shutil.copyfile(path, folder / path.name)
    return {"file": path.name}


if __name__ == "__main__":
    cyclopts.run(main)
