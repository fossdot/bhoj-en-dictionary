# bhoj — Bhojpuri dictionary + LLM data pipeline

A Bhojpuri→English dictionary built on [dictpress](https://dict.press)
(Kailash Nadh's dictionary webserver), designed so the same curated data
feeds Bhojpuri LLM development: seed lexicon, parallel sentence pairs, and
instruction-tuning data are generated from one canonical source.

## Architecture

```
sources (Wiktionary, …)
      │  pipeline/fetch_*.py
      ▼
data/canonical/*.jsonl        ← single source of truth (one entry per line)
      │                                │
      │ pipeline/to_dictpress.py       │ pipeline/to_training.py
      ▼                                ▼
dictpress/import.csv          data/training/
  → public dictionary site      ├─ lexicon.tsv        bho ⇄ en word pairs
                                ├─ parallel.jsonl     bho ⇄ en sentence pairs
                                └─ instructions.jsonl chat-format SFT data
```

The canonical JSONL is authoritative; both the dictionary site and the
training exports are regenerated from it, so they never diverge.

## Canonical entry schema

```json
{
  "word": "अगुआ",
  "lang": "bho",
  "script": "Deva",              // Deva | Kthi (Kaithi) | Latn
  "translit": ["aguā"],
  "phones": ["/ə.ɡu.aː/"],
  "tags": ["gender:m"],
  "senses": [
    {
      "pos": "noun",
      "gloss": "leader, head",   // English gloss → bho→en direction
      "examples": [{"bho": "…", "en": "…", "translit": "…"}]
    }
  ],
  "source": "en.wiktionary.org",
  "source_url": "https://en.wiktionary.org/wiki/अगुआ#Bhojpuri",
  "license": "CC BY-SA 4.0"
}
```

Usage examples are first-class: they're the highest-value data for LLM
training (parallel text), even though a dictionary UI treats them as
decoration.

## Quick start

```sh
# 1. Fetch sources → canonical JSONL (cached; --refresh to refetch)
python3 pipeline/fetch_wiktionary.py

# 2. Generate dictpress import CSV + LLM training exports
python3 pipeline/to_dictpress.py data/canonical/*.jsonl > dictpress/import.csv
python3 pipeline/to_training.py data/canonical/*.jsonl

# 3. Set up + run the dictionary site (dictpress v5 ships Linux binaries → Docker on macOS)
cd dictpress
docker run --rm -v "$PWD:/work" -w /work/app alpine \
  ./dictpress --config ../config.toml --db ../data.db install
docker run --rm -v "$PWD:/work" -w /work/app alpine \
  ./dictpress --config ../config.toml --db ../data.db import --file ../import.csv
docker run -d --name bhoj-dict -p 9000:9000 -v "$PWD:/work" -w /work/app alpine \
  ./dictpress --config ../config.toml --db ../data.db --site site
```

Then open <http://localhost:9000> (site) or <http://localhost:9000/admin>
(admin, credentials in `dictpress/config.toml` — change them). Search
supports romanized phonetic lookup: `agua` finds अगुआ, via the bundled
IndicPhone Devanagari tokenizer.

`dictpress/app/` (binary + default site theme) is not committed; download
from [dictpress releases](https://github.com/knadh/dictpress/releases)
(v5.0.0-rc5, `aarch64-unknown-linux-musl` for Apple Silicon Docker).

## Data sources

| Source | Status | Size | License |
|---|---|---|---|
| [English Wiktionary bho lemmas](https://en.wiktionary.org/wiki/Category:Bhojpuri_lemmas) | ✅ imported | 421 entries, 477 senses, 32 example pairs | CC BY-SA 4.0 |
| en-Wiktionary translation tables (en→bho) | planned | unknown | CC BY-SA 4.0 |
| [Bhojpuri Wikipedia](https://bh.wikipedia.org) | planned | ~1.8M words | CC BY-SA |
| [BHLTR (JNU)](https://github.com/shashwatup9k/bho-resources) | planned | 45k mono sents + en-bho parallel | CC BY-**NC**-SA ⚠ non-commercial |
| Native-speaker submissions | planned | — | via dictpress submission queue |

Notes for LLM work:

- Bhojpuri is **not** in IndicCorpV2 or Sangraha (not one of the 22
  scheduled languages) — the corpus has to be assembled here.
- NLLB/FLORES-200 and MADLAD-400 do cover `bho` — useful for MT
  bootstrapping and synthetic data later.
- Realistic model path: continued pretraining / fine-tuning of a
  Hindi-strong open base (Devanagari, high lexical overlap), not
  pretraining from scratch.

## Layout

```
pipeline/
  fetch_wiktionary.py   Wiktionary → canonical JSONL (raw pages cached in data/raw/)
  to_dictpress.py       canonical JSONL → dictpress import CSV
  to_training.py        canonical JSONL → lexicon.tsv / parallel.jsonl / instructions.jsonl
data/
  raw/                  raw source pulls (cache)
  canonical/            canonical JSONL, one file per source
  training/             generated LLM exports
dictpress/
  config.toml           dictpress v5 config (bhojpuri → english)
  import.csv            generated import file
  app/                  dictpress binary + theme (gitignored, see Quick start)
```
