# The `aipress24` command: design

Status: phase 1 is implemented; the rest is defined so that it fits later without renaming anything.

## Purpose

Publish existing documents in bulk, safely: a first import, a re-run after a failure, a correction across many documents, and later additions are the same operation. A single document is a batch of one. Writing a text in the terminal and replacing the site's editor are out of scope.

## Grammar

```
aipress24 <noun> <verb> [ARGUMENT...] [--option...]
```

- A noun is singular, hyphenated, and names the same thing as the API: `press-release`, never "news" or "release".
- A verb means the same thing under every noun. A noun only has the verbs that apply to it.
- There is no default noun, no default verb and no alias: one way to say each thing.
- Every verb that takes documents takes several.
- A command that is not implemented does not exist: it is not listed in the help.
- Commands, options, messages and document keys are in English. Classification values stay as the site has them.

## Nouns

| Noun | What it is | Verbs | Phase |
|---|---|---|---|
| `press-release` | a press release of yours | all the content verbs | 1 |
| `article` | an article of yours (journalists) | all the content verbs | 2 |
| `event` | an event of yours | all the content verbs | 2 |
| `post` | a message of yours on the wall | `check` `status` `publish` `delete` `list` `show` | 1 |
| `catalog` | the local table of the documents to sort and classify | `create` `update` `status` | 1 |
| `vocabulary` | the values a classification accepts | `list` `search` | 1 |
| `publisher` | an organisation you may publish for | `list` | 1 |
| `auth` | your access to a site | `login` `logout` `status` | 1 |
| `enquiry-notice` `mission` `project` `job` `product` | other contents of yours | `list` `show` | 3 |
| `member` `organisation` `business-wall` | the directories | `list` `show` | 3 |

## Content verbs

They are the same for `press-release`, `article` and `event`. Each states the result wanted, not the operation: run twice, it does nothing the second time.

| Verb | Result | Argument | Writes to the site |
|---|---|---|---|
| `check` | every problem of every document is reported | source | no |
| `status` | each document is compared with the site | source | no |
| `draft` | each document is on the site, as a draft | source | yes |
| `publish` | each document is public | source or item | yes, visible |
| `unpublish` | each item is a draft again | source or item | yes, visible |
| `delete` | each item is gone | source or item | yes, final |
| `list` | your items; `--public` for everyone's public ones | none | no |
| `show` | one item, with its page | source or item | no |
| `new` | a folder to fill in (phase 2) | path | no |

A **source** is a path: a document, a folder holding one, or a catalog. An **item** is something on the site, given by its id or the URL of its page. A path made only of digits is written `./123`.

`draft` never changes what the public sees: a document already public is reported and left alone. Only `publish` updates a public text. `publish` on a source sends what changed and then publishes; on an item it publishes what is on the site, and sends nothing.

## Documents

A document is a Markdown file with a YAML front matter, or an HTML file, next to its images. Word and PDF come later. Keys are the same for the three contents where they mean the same thing:

| Key | API field | Press release | Article | Event |
|---|---|---|---|---|
| `title` | `titre` | required | required | required |
| `summary` | `chapo` | yes | yes | yes |
| (body) | `contenu` | to publish | to publish | to publish |
| `genre` `section` `topic` | same | to publish | yes | no |
| `sector` | same | to publish | yes | yes |
| `reference` | `external_ref` | required | (1) | (1) |
| `published_at` | same | yes | (1) | no |
| `embargoed_until` | same | yes | no | no |
| `publisher` | `publisher_id` | yes | no | yes |
| `language` `address` `country` `city` | `language` `address` `pays_zip_ville` `pays_zip_ville_detail` | yes | no `city` | no `city` |
| `images` | carousel | yes | (1) | (1) |
| `event_type` `mode` `platform` `access_details` `url` `start` `end` | same, `start_time`, `end_time` | no | no | yes |

(1) Needs the API to accept it first, as it now does for press releases.

`publisher` is an id or an exact name from `publisher list`. It defaults to your own organisation; without either, `check` fails. `published_at` is a date or a date and time with its zone; a bare date means 6:00 in Paris, so that today is rarely still to come. Images found in the body move to the carousel, after the listed ones, and `check` says so. Images must be files under the document's folder, or the catalog's.

Raw HTML is kept, less what the site cannot show (scripts, frames, forms…). Relative links are resolved against `reference` when it is a URL. An HTML page gives its title, summary, reference and date from its usual metadata; its classification comes from a catalog. Keys that are not in this table are ignored and mentioned, as existing documents have their own.

`reference` is what prevents duplicates, so it is explicit: best the URL of the original, otherwise any stable name. It is not derived from the path, as moving a file would create a second item.

## Catalog

Documents come mixed: of 78 news of abilian.com, 10 are press releases and several others are events. A catalog sorts and classifies them in a spreadsheet, and can be sent to someone for review.

```
aipress24 catalog create content/fr/news -o abilian.csv
aipress24 catalog update abilian.csv content/fr/news
```

It is a CSV file, one line for each document:

| Column | Meaning |
|---|---|
| `source` | path, relative to the catalog; `archive.zip#id` for a message of an archive |
| `type` | `press-release`, `article`, `event`, `post` or `skip`; empty while undecided |
| `reference` `title` `published_at` `publisher` `genre` `section` `topic` `sector` | as in a document |
| `popularity` | for a message, how many liked or shared it; never sent |
| `note` | free text, never sent |

- `create` fills in what the documents say and refuses to overwrite a file. `update` appends the new documents and touches no existing line.
- A cell that is not empty wins over the document's front matter. An empty cell does not clear anything.
- A content verb takes the lines of its own type: `press-release draft abilian.csv` ignores events, `skip` and undecided lines, and says how many.
- The catalog holds decisions, never results: no id, status or URL is written to it. `catalog status` shows those, for all types.

Options of content verbs on a catalog: `--only PATTERN` (repeatable, matches `source` or `reference`) and `--limit N`.

## Archives of social networks

`catalog create` also takes the archive of an account, when it is named: Mastodon or Twitter (`.zip`), or Bluesky (`.car`). Each message is a line, of type `post` or, for a reason given in `note`, `skip`:

| Message | Line |
|---|---|
| original and public, with the rest of its thread | `post` |
| reply to someone, or in the thread of someone else | `skip` |
| begins with a mention (Mastodon): a reply whose parent was deleted | `skip` |
| unlisted (Mastodon); withheld or sensitive, or from an account that was protected at some time (Twitter) | `skip` |
| quotes a message, holds the text of someone else (`“@x: …”`, `RT @x`), or nothing but a link (Twitter) | `skip` |
| same text within 3 days as one already listed, on the same network or another | `skip`, `same as URL` |
| nothing to read and no image | `skip` |
| private, or someone else's (boost, repost, retweet) | no line, and it cannot be asked for |

A type can be changed, but a private message is never read, even when a line names it. Archives are compared in the order they are given, so give first the one that holds images: Bluesky's does not. The reference of a message is its URL, so a newer archive of the same account only adds what is new. The `title` column is the beginning of the text, to recognise it, and is not sent.

Links are written in full, mentions as `@name@server`, and the declared language is ignored, as it is often wrong. Only the files of public messages and their images are opened: not the likes, bookmarks, direct messages, deleted messages or addresses. Shortened links (`bit.ly`, `buff.ly`…) are kept as they are.

## Posts

A post has no draft and cannot be modified, so `post` has neither `draft` nor `unpublish`, and `publish` takes catalogs only. It answers `published`, `unchanged`, `deleted` (it was sent from here, and is not on the site any more; `--recreate` sends it again) or `different` (delete it, then publish it again). A post is sent with its images in one request, at its own date, and shows where it was first published.

`post delete catalog.csv` undoes an import, and takes `--only` and `--limit`. The site allows 50 new posts and 1000 imported ones in 24 hours: beyond, the command stops, and the same one does the rest the next day. Posting needs the `write:social` scope, and `read:self`.

## Sending

Everything is read and checked before the first write. If a document is invalid, nothing is sent; `--skip-invalid` sends the others. Then each document is sent on its own: a failure does not stop the next ones, except a refused token, which stops everything. Running the command again does what is left.

The command remembers what it last sent in `.aipress24/`, next to the catalog, or in the document's folder when there is none. This is a cache and is not mentioned to the user: without it, documents are found again by `reference`.

| Document since last sent | On the site since | `draft` / `publish` |
|---|---|---|
| new | absent | create |
| unchanged | unchanged | nothing to send |
| changed | unchanged | update |
| unchanged | changed | keep the site's version |
| changed | changed | conflict: skipped, unless `--overwrite` |
| any | deleted | skipped, unless `--recreate` |
| never sent from here | present, found by `reference` | conflict: skipped, unless `--overwrite` |

So a draft corrected on the site during review is published as corrected. Conflicts are reported together at the end, with the fields that differ, and are never asked about one by one.

A creation whose answer was lost is found again by `reference` the next time, and known to be ours. Only reads are retried, on a network error or a 5xx.

## Confirmation

`publish`, `unpublish` and `delete` show what they are about to do and ask once for the whole batch:

```
$ aipress24 press-release publish abilian.csv
Publish 10 press releases on https://aipress24.com, for Abilian:
  8 to create, 1 draft to publish, 1 public text to update
  dated from 2014-10-29 to 2025-09-26
Continue? [y/N]
```

`--yes` answers it, and is required when there is no terminal. It never implies `--overwrite` or `--recreate`. `--dry-run` shows the same and stops. `draft` does not ask: nobody else sees the result.

## Output

One line for each document, then a summary, then what to do next:

```
$ aipress24 press-release draft abilian.csv
created   Deux financements européens pour Hop3   https://aipress24.com/wip/communiques/x…/
kept      Abilian en route vers les Big Data      https://aipress24.com/wip/communiques/x…/
conflict  Euclidia                                title, summary changed here and on the site
10 press releases: 8 created, 1 kept, 1 conflict (--overwrite to replace the site's version)
```

Results go to stdout; questions, progress and errors to stderr. `--json` prints one JSON object per line instead, with `result`, `title`, `source`, `reference`, `id`, `status`, `page`, `problems` and `warnings`.

`check` answers `ready`, `draft-only` (something is missing to publish) or `invalid`. Without a token, it does not check the classification nor the publisher, and says so.

| Exit status | Meaning |
|---|---|
| 0 | the result stated by the verb holds for every document |
| 1 | it does not for some: invalid, failed, conflict, deleted; or the site refused |
| 2 | the command line is wrong, or a confirmation is missing |
| 130 | interrupted; running it again does what is left |

## Options common to all commands

| Option | Variable | Meaning |
|---|---|---|
| `--site URL` | `AIPRESS24_SITE` | the site, by default `https://aipress24.com` |
| `--json` | | output for programs |
| `--help`, `--version` | | |

They are accepted anywhere on the line. The token is never an option, as it would show in the process list: it comes from `AIPRESS24_TOKEN`, or from `auth login`, which asks for it, verifies it and stores one token per site in mode 600.

## The other nouns

- `auth status` shows the site, the account, its organisation and how many organisations it may publish for.
- `publisher list` shows id and name, your own organisation first.
- `vocabulary list press-release.genre` prints one value per line. `vocabulary search cloud` looks in every vocabulary, ignoring case and accents, and prefixes each value with its field. A refused value in `check` comes with the closest ones.

## Phases

1. `auth`, `publisher`, `vocabulary`, `catalog`; `press-release` with `check`, `status`, `draft`, `publish`, `unpublish`, `delete`, `list`, `show`; Markdown and HTML. Needs the API with `external_ref`, `published_at`, `/me/publishers` and `_links.page` deployed. `post`, with `/me/posts` deployed.
2. `article` and `event`, once the API gives them `external_ref`, images and their vocabularies; `press-release new`.
3. Word and PDF, then the read-only nouns.
