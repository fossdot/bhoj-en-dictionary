# भोज — Bhojpuri → English dictionary

An open Bhojpuri→English dictionary, built so the same data also trains a
Bhojpuri language model. **13,481 headwords, 23,628 definitions**, every entry
under CC BY-SA 4.0 or CC BY 4.0. It is the only openly licensed,
machine-readable Bhojpuri dictionary we know of.

### How much of this is verified

Bhojpuri has no large hand-built lexicon to copy from, so most entries are
assembled from adjacent sources and then checked. Every entry carries the
evidence behind it, and `pipeline/triage_headwords.py` sorts them by how
strongly that evidence holds:

**Every headword is attested in a curated Bhojpuri source.**
`pipeline/attest_headwords.py` checks each one against hand-annotated lexica
(the UD Bhojpuri treebank, the POS-tagged BHLTR corpus, Wikidata bho lexemes,
en-Wiktionary's Bhojpuri entries, GATITOS) and text written or professionally
translated as Bhojpuri (Bhojpuri Wikipedia, BHLTR, VarDial, NLLB). Web crawl
does not count — its `bho` label is a classifier's guess — and FLORES is
excluded so the benchmark stays out of the dictionary.

| | entries | |
|---|---:|---|
| `gold` | 10,959 | in a hand-annotated Bhojpuri lexicon |
| `authored` | 7,304 | used in Bhojpuri-authored text |

How strongly a source asserts the word is *specifically* Bhojpuri, rather than
shared with Hindi, is tracked separately by `pipeline/triage_headwords.py`:

| | entries | |
|---|---:|---|
| `attested` | 4,628 | a source explicitly labelled the word Bhojpuri |
| `shared-attested` | 2,994 | Hindi-sourced, headword independently attested |
| `unverified` | 10,641 | shared Indo-Aryan vocabulary; awaiting a speaker |

Unverified entries also carry a `conf:` tag and a `bho_ratio` — the share of
corpus sentences containing the word that are Bhojpuri-marked rather than
Hindi-marked (`pipeline/score_bho_context.py`). Reviewers work lowest-first.

Only 33 entries currently have usage examples. Adding them is the highest-value
contribution, both for readers and for training data.

Native speakers verify and improve the entries in two ways: anyone can suggest
a word or an edit on the dictionary site, and students in the Hikmat Foundation
*school to livelihood* programme review the entries in batches of 100 through
the review app.

## What is here

| Folder | What |
|---|---|
| `data/canonical/` | The dictionary: one JSON line per word. Single source of truth. |
| `dictpress/` | The public site, served by [dictpress](https://dict.press). |
| `app/review/` | Review app for students and teachers. |
| `pipeline/` | Scripts that build the dictionary and the LLM training data from sources. |
| `deploy/` | Everything needed to run it on one server. |
| `docs/` | [Architecture](docs/architecture.md) · [Data sources & licences](docs/data-sources.md) · [Training a model](docs/training.md) |

## Run it locally

```sh
make dict            # dictionary site → http://localhost:9000  (needs Docker)
make review-import   # load the dictionary into the review app
make review-run      # review app → http://localhost:9100
```

The dictpress binary is not in the repo; `deploy/setup.sh` shows how to fetch
it, or grab `v5.0.0-rc5` from [dictpress releases](https://github.com/knadh/dictpress/releases)
into `dictpress/app/`.

## Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md): suggest a word on the site, open an
issue, send a pull request, or review batches in the app.

## Go live

See [deploy/README.md](deploy/README.md): one VPS, Docker Compose, HTTPS, backups.

## Licence

Dictionary data: per-entry `license` field, CC BY-SA 4.0 or CC BY 4.0.
Site theme: AGPL-3.0 (from dictpress). Corpus and code: see
[docs/data-sources.md](docs/data-sources.md#licensing).
