# AIpress24 Python client

A dependency-free Python client for the AIpress24 public API (`/api/v1`), and an `aipress24` command that publishes existing press releases in bulk.

## Install

Python 3.11 or later is needed.

Until the package is on PyPI:

```bash
pip install git+https://github.com/aipress24/aipress24-sdk-python      # the client, standard library only
uv tool install "aipress24-client[cli] @ git+https://github.com/aipress24/aipress24-sdk-python"  # the command
```

## Authentication

The API is authenticated with a **bearer token**. Ask an AIpress24 administrator to issue one (they run `flask api-token issue --email you@example.com`). A token carries scopes — `read:content`, `read:organisations`, `read:directory`, `read:self` (your own `/me` data) and `write:content` (author & publish your own content) — and can be revoked at any time.

## Publishing existing press releases

Commands are `aipress24 <noun> <verb>`. The [design](docs/cli.md) defines them all; only `press-release` contents are sent so far, and the archives of Mastodon and Bluesky accounts can be sorted (`catalog create archive.zip repo.car`, `post check`).

```bash
aipress24 auth login                                  # or set AIPRESS24_TOKEN
aipress24 catalog create content/news -o news.csv     # list the documents in a table
aipress24 vocabulary search cloud                     # look for classification values
```

In the table, give a `type` to each line (`press-release`, or `skip`) and fill in `reference`, `genre`, `section`, `topic` and `sector`. Then:

```bash
aipress24 press-release check news.csv                # every problem, sending nothing
aipress24 press-release draft news.csv                # have them on the site, as drafts
aipress24 press-release publish news.csv              # have them public, after a confirmation
aipress24 press-release status news.csv
```

Each command states a result: run again, it does what is left. What was corrected on the site is kept, what was deleted there is not created again, and what changed on both sides is reported as a conflict.

A document is a Markdown or an HTML file, and can also be given alone, without a table:

```markdown
---
title: "Acme lance le Widget"
reference: https://acme.example/news/widget/   # prevents duplicates
published_at: 2025-01-23                       # from 2000 on; now, if absent
summary: Un widget plus léger.
genre: …
section: …
topic: …
sector: …
publisher: Acme                                # your own organisation, if absent
country: FRA
city: FRA / 75001 Paris
images:
  - file: cover.jpg                            # the first one is the cover
    caption: Le Widget
    copyright: Acme
---

Le texte du communiqué, en **Markdown**.
```

The token needs `read:self` and `write:content`. `--site` or `AIPRESS24_SITE` choose another site than `https://aipress24.com`, and `--json` prints results for programs. [`examples/abilian_news.py`](examples/abilian_news.py) converts a whole site.

## Usage from Python

```python
from aipress24_client import Client, ApiError

api = Client(token="a24_your_token_here", base_url="https://aipress24.com")

# Discovery entry point (public): link relations + docs URLs.
print(api.root()["_links"].keys())

# One page (offset/limit pagination, HATEOAS _links in every payload):
page = api.articles(limit=10)
print(page.total, "articles;", len(page), "on this page")
for article in page:
    print(article["title"], "->", article["_links"]["self"]["href"])

# Walk every page automatically, following the `next` link:
for member in api.iter("members", limit=50):
    print(member["full_name"], member.get("job_title"))

# Fetch a single resource:
one = api.article(page.items[0]["id"])

# Errors surface as ApiError with the HTTP status + JSON body:
try:
    api.members()  # needs the read:directory scope
except ApiError as exc:
    print(exc.status, exc.payload)
```

Responses are typed (`Article`, `Member`, …: `TypedDict`s generated from the spec). The client only ever sends the token to `base_url`: it refuses links to another origin and does not follow redirects.

## Public read resources

| Method | Endpoint | Scope |
|---|---|---|
| `articles()` / `article(id)` | `/api/v1/articles` | `read:content` |
| `press_releases()` / `press_release(id)` | `/api/v1/press-releases` | `read:content` |
| `events()` / `event(id)` | `/api/v1/events` | `read:content` |
| `organisations()` / `organisation(id)` | `/api/v1/organisations` | `read:organisations` |
| `business_walls()` / `business_wall(id)` | `/api/v1/business-walls` | `read:organisations` |
| `members()` / `member(id)` | `/api/v1/members` | `read:directory` |

## Owner-scoped data & writes (`/me`)

`me()` returns your own profile (`read:self`). Your own records — in any status, including drafts — are read generically (`read:self`), and the content types can be authored and published (`write:content`). `collection` is a path segment such as `me/press-releases`, `me/articles` or `me/events`.

| Method | Endpoint | Scope |
|---|---|---|
| `me()` | `GET /api/v1/me` | `read:self` |
| `list("me/articles")` / `get_one("me/articles", id)` | own articles (also `me/press-releases`, `me/events`, `me/enquiry-notices`, `me/missions`, `me/projects`, `me/jobs`, `me/products`) | `read:self` |
| `create(collection, data)` | `POST /api/v1/{collection}` | `write:content` |
| `update(collection, id, data)` | `PATCH /api/v1/{collection}/{id}` | `write:content` |
| `publish(collection, id)` / `unpublish(collection, id)` | `POST …/{id}/publish` \| `/unpublish` | `write:content` |
| `delete(collection, id)` | `DELETE /api/v1/{collection}/{id}` | `write:content` |

```python
# Author a press release on your own behalf, then publish it.
pr = api.create(
    "me/press-releases",
    {
        "titre": "Acme launches …",
        "contenu": "<p>…</p>",
        "genre": "…",
        "section": "…",
        "topic": "…",
        "sector": "…",
    },
)
with open("cover.jpg", "rb") as cover:
    api.add_press_release_image(pr["id"], cover.read(), "cover.jpg", caption="…")
api.publish("me/press-releases", pr["id"])
```

Publishing also requires `genre`, `section`, `topic` and `sector`, with values from `press_release_vocabularies()`. Upload the images first: the first one is the cover.

| Method | Endpoint | Scope |
|---|---|---|
| `publishers()` | `GET /me/publishers` | `read:self` |
| `press_release_vocabularies()` | `GET /vocabularies/press-releases` | any |
| `press_release_images(id)` | `GET /me/press-releases/{id}/images` | `read:self` |
| `add_press_release_image(id, content, filename, caption, copyright)` | `POST …/images` | `write:content` |
| `delete_press_release_image(id, image_id)` | `DELETE …/images/{image_id}` | `write:content` |

Interactive documentation (OpenAPI) is served live at `https://aipress24.com/api/v1/docs` (Swagger UI) and `/api/v1/redoc`, with the raw spec at `/api/v1/openapi.json`.

## Development

The package is in `src/`, the generator in `scripts/`. `make check` runs the linters and the tests. `src/aipress24_client/_generated.py` (the typed models and the list of collections) is generated from `openapi.json`, a copy of the application's spec: `make generate` refreshes both from a checkout of `aipress24` next to this one, or from `SPEC=path/to/openapi.json`.

## License

Apache-2.0, see `LICENSE`. The AIpress24 application itself is under AGPL-3.0.
