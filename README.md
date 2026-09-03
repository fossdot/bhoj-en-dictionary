# भोज — Bhojpuri → English dictionary

An open Bhojpuri→English dictionary with example sentences, built so the same
data also trains a Bhojpuri language model. **20,254 headwords, 30,432
definitions**, every entry under CC BY-SA 4.0 or CC BY 4.0. It is the only
openly licensed, machine-readable Bhojpuri dictionary we know of.

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
