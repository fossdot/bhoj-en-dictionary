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

### Dictionary (→ `data/canonical/`, all in dictpress)

| Source | Yield | License |
|---|---|---|
| [en-Wiktionary bho lemmas](https://en.wiktionary.org/wiki/Category:Bhojpuri_lemmas) | 421 entries, 477 senses, 32 example pairs | CC BY-SA 4.0 |
| en-Wiktionary translation tables (711 pages mined) | 742 bho words, 768 pairs | CC BY-SA 4.0 |
| **merged** | **998 headwords, 1,239 definitions** | |

### Corpus (→ `data/corpus/`, see `STATS.md` for exact counts)

| Source | Yield | License |
|---|---|---|
| [HPLT v2](https://hplt-project.org) `bho_Deva` | 6.6M words (prob≥0.9 + Devanagari filter) | CC0 (web text) |
| [MADLAD-400](https://huggingface.co/datasets/allenai/MADLAD-400) `bho` clean+noisy | 2.7M + 6.9M words ("noisy" tier is decent bho journalism) | ODC-BY |
| [Bhojpuri Wikipedia](https://bh.wikipedia.org) dump | 1.19M words | CC BY-SA 4.0 |
| [OPUS NLLB](https://opus.nlpl.eu) mined bho–en bitext | 8.7k pairs @LASER≥1.15, 121k @≥1.10 (of 2.43M raw) | ODC-BY |
| [FLORES-200](https://github.com/facebookresearch/flores) dev+devtest | 2,009 pro-translated pairs — **EVAL ONLY, never train** | CC BY-SA 4.0 |
| OPUS wikimedia / Tatoeba | 1,194 / 42 pairs | CC BY-SA / CC BY |
| [BHLTR (JNU)](https://github.com/shashwatup9k/bho-resources) | 29.5k parallel + 43k mono lines — kept in `-NC` files | CC BY-**NC**-SA ⚠ |
| [UD Bhojpuri BHTB](https://github.com/UniversalDependencies/UD_Bhojpuri-BHTB) | 268 sentences (+POS trees) | CC BY-SA 4.0 |

**Bottom line: `mono/all-dedup.txt` = 12.77M words (335k lines) of
deduplicated, commercial-safe Bhojpuri text; ~160k parallel pairs; 114k-example
SFT bundle (`sft.jsonl`), 143k with NC sources (`sft-nc.jsonl`).**

Dead ends checked so far: kaikki.org (no bho extract), IndicCorpV2/Sangraha/BPCC
(bho not a scheduled language, excluded), eBible (no open bho scripture),
OLDI-seed (no bho), Leipzig + StoryWeaver (bot-walled), Wikimedia incubator
Wt/bho (~30 stubs), Wikidata lexemes (30, subset of Wiktionary).

Notes for LLM work:

- Realistic model path: continued pretraining / fine-tuning of a
  Hindi-strong open base (Devanagari, high lexical overlap), not
  pretraining from scratch.
- FLORES-200 files are named `*-EVAL-ONLY` for a reason: they're the
  benchmark. Keep them out of every training set.
- NLLB `bho` side and web crawls carry Awadhi/Hindi/Magahi contamination;
  the LASER-score tiers and Devanagari filters here are first-pass cleanup,
  not the last word.

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
  app/                  dictpress binary + theme (gitignored, see Quick start)
```

## Rebuild everything

```sh
python3 pipeline/fetch_wiktionary.py
python3 pipeline/fetch_wiktionary_translations.py
python3 pipeline/extract_bhwiki.py          # needs data/raw/bhwiki dump
python3 pipeline/build_corpus.py            # needs data/raw/{opus,flores,madlad,hplt,bho-resources,UD_Bhojpuri-BHTB}
python3 pipeline/to_dictpress.py data/canonical/*.jsonl > dictpress/import.csv
python3 pipeline/to_training.py data/canonical/*.jsonl
python3 pipeline/assemble_sft.py            # add --include-nc for the NC bundle
```
