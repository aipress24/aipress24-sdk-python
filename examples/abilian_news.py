# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
#
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts>=5.5,<6", "pyyaml>=6"]
# ///
"""Convert the news of abilian.com into documents, and list them in a catalog.

    uv run examples/abilian_news.py ../../web/abilian.com ../abilian-news
    uv run aipress24 press-release check ../abilian-news/catalog.csv

Running it again rewrites the documents, but not the catalog.
"""

from __future__ import annotations

import csv
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import cyclopts
import yaml

SITE = "https://abilian.com"
DEFAULT_ILLUSTRATION = "abilian.png"


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

COLUMNS = (
    *("source", "type", "reference", "title", "published_at", "publisher"),
    *("genre", "section", "topic", "sector", "note"),
)

_IMAGE = re.compile(r"""(!\[[^\]]*\]\(|<img[^>]*?src=")([^)\s"]+)""")


def main(site: Path, output: Path, /) -> None:
    """Convert the news.

    Parameters
    ----------
    site
        The Lektor project of abilian.com.
    output
        Where to write one folder for each news, and the catalog.
    """
    rows = []
    for source in sorted((site / "content" / "fr" / "news").glob("*/contents.lr")):
        news = parse_lektor(source.read_text(encoding="utf-8"))
        if "pub_date" in news:
            slug = source.parent.name
            convert(site, slug, news, output / slug)
            rows.append(describe(slug, news))
    catalog = output / "catalog.csv"
    if not catalog.exists():
        with catalog.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, COLUMNS, restval="")
            writer.writeheader()
            writer.writerows(rows)
    print(f"{output}: {len(rows)} documents")


def describe(slug: str, news: dict[str, str]) -> dict[str, str]:
    """The line of a news in the catalog: only press releases have a type."""
    line = {
        "source": f"{slug}/document.md",
        "reference": url_of(slug),
        "title": title_of(news),
        "published_at": news["pub_date"],
    }
    if slug in RELEASES:
        line |= {"type": "press-release", **vars(RELEASES[slug])}
    return line


def convert(site: Path, slug: str, news: dict[str, str], folder: Path) -> None:
    source = site / "content" / "fr" / "news" / slug
    folder.mkdir(parents=True, exist_ok=True)
    illustrations = site / "assets" / "static" / "illustrations"
    illustration = illustrations / news.get("illustration", DEFAULT_ILLUSTRATION)
    if illustration.suffix == ".svg":
        illustration = illustrations / DEFAULT_ILLUSTRATION
    shutil.copyfile(illustration, folder / illustration.name)

    def localize(match: re.Match[str]) -> str:
        url = match[2]
        path = site / "assets" / url[1:] if url.startswith("/") else source / url
        if not path.is_file():
            return match[0]
        shutil.copyfile(path, folder / path.name)
        return f"{match[1]}{path.name}"

    matter = {
        "title": title_of(news),
        "summary": plain_text(news.get("description", "")),
        "reference": url_of(slug),
        "published_at": news["pub_date"],
        "language": "fr",
        "country": "FRA",
        "images": [illustration.name],
    }
    header = yaml.safe_dump(matter, allow_unicode=True, sort_keys=False, width=10**6)
    body = _IMAGE.sub(localize, news.get("body", "").replace("\ufffc", ""))
    # Blank lines around, as a line before '---' would become a title.
    body = re.sub(r"<hr\s*/?>", "\n\n---\n\n", body)
    (folder / "document.md").write_text(
        f"---\n{header}---\n\n{body.strip()}\n", encoding="utf-8"
    )


def url_of(slug: str) -> str:
    return f"{SITE}/fr/news/{slug}/"


def title_of(news: dict[str, str]) -> str:
    return re.sub(r"^\[[^\]]*\]\s*", "", news["title"])


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


def plain_text(text: str) -> str:
    return " ".join(text.replace("*", "").split())


if __name__ == "__main__":
    cyclopts.run(main)
