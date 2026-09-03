# Architecture

```
sources (Wiktionary, …)                       reviewers (app/review)
      │  pipeline/fetch_*.py                    │  verify entries in batches of 100;
      ▼                                         │  phase 1: seen once; phase 2: cross-review
data/canonical/*.jsonl  ◀───────────────────────┘  app/review/apply_verdicts.py
  ← single source of truth (one entry per line)     (logged in data/cleaning/)
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

## Layout

```
pipeline/
  fetch_wiktionary.py               en-Wiktionary bho lemma pages → canonical JSONL
  fetch_wiktionary_translations.py  en-Wiktionary translation tables → canonical JSONL
  extract_bhwiki.py                 bhwiki XML dump → data/corpus/mono/bhwiki.txt
  build_corpus.py                   all raw sources → data/corpus/{parallel,mono} + STATS.md
  to_dictpress.py                   canonical JSONL (merged by headword) → dictpress import CSV
  to_training.py                    canonical JSONL → lexicon.tsv / parallel.jsonl / instructions.jsonl
  assemble_sft.py                   instructions + corpus parallel → sft.jsonl (--include-nc → sft-nc.jsonl)
data/
  raw/                  raw source pulls (gitignored; refetch via pipeline + URLs in scripts)
  canonical/            canonical JSONL, one file per source
  corpus/               normalized corpora (gitignored; rebuild with build_corpus.py)
  training/             LLM exports (large sft*.jsonl gitignored)
dictpress/
  config.toml           dictpress v5 config (bhojpuri → english)
  import.csv            generated import file
  site/                 site theme (upstream default + Bhoj branding)
  app/                  dictpress binary + tokenizers (gitignored; deploy/setup.sh downloads it)
app/review/             student review app (Flask + SQLite) — see its README
deploy/                 production stack: Docker Compose + Caddy — see its README
eval/                   chrF scorer + evaluation protocol
docs/                   this file, data-sources.md, training.md
```

## Rebuild everything

```sh
make fetch   # Wiktionary + GATITOS → canonical JSONL
make data    # corpus + dictionary CSV + training exports (needs data/raw/ downloads)
make dict    # fresh DB + import + restart the dictpress container
```

(See the Makefile for the underlying `pipeline/*.py` commands; raw-source
download URLs are documented in each fetcher/processor script.)

## Evaluation

FLORES-200 bho files are the benchmark — never train on them. See
`eval/README.md` for the protocol and `eval/score.py` for a dependency-free
chrF2 scorer.
