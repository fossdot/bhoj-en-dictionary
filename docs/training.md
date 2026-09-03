# From this data to a Bhojpuri LLM

What exists here (as of 2026-08): ~19.1M words (~28M tokens) of deduplicated
monolingual Bhojpuri, ~180k parallel bho–en pairs of mixed quality including
~15k professional translations, a 5.6k-pair lexicon, and a held-out FLORES +
NLLB-MD-test benchmark. That is enough for **adaptation**, not from-scratch
pretraining (which wants billions of tokens).

## Recipe (in order of leverage)

### 1. Pick a Hindi-strong open base

Bhojpuri is Devanagari with heavy lexical overlap with Hindi; transfer from a
Hindi-capable base is the whole game. Candidates to evaluate (run FLORES
bho→en / en→bho zero-shot first, pick the strongest starting point):

- Gemma family (strong Indic coverage for an open model)
- Llama 3.x family
- Qwen family
- Indic-focused models: Sarvam, AI4Bharat/Airavata lineage, Krutrim

Tokenizer fertility matters more than benchmark scores. Measured on this
corpus (`pipeline/measure_fertility.py`, 20k-line sample):

| tokenizer | tokens/word | chars/token |
|---|---:|---:|
| IndicBERTv2 (encoder — reference point, not a chat base) | 1.48 | 3.46 |
| Sarvam-1 | 1.77 | 2.90 |
| Qwen3 | 4.71 | 1.09 |

A Sarvam-class Indic tokenizer fits ~2.7× more Bhojpuri into a context
window than Qwen3, which shreds Devanagari near byte level. Gemma/Llama
tokenizers are gated on HF — drop their `tokenizer.json` into
`data/raw/tokenizers/` and rerun to compare.

### 2. Continued pretraining (CPT)

- Data: `mono/all-dedup-lid-bho.txt` (LID-filtered, ~26M tokens; the unfiltered
  `all-dedup.txt` is ~28M) + optionally the bho side of
  parallel data. Mix in 5–15% Hindi + English replay data to prevent
  catastrophic forgetting.
- 2–4 epochs over the bho data is defensible at this scale; watch held-out
  perplexity on a slice you exclude up front.
- LoRA (r=64+ on all linear layers) if compute-constrained; full fine-tune of
  a small model (2–9B) if a single 80GB GPU or better is available.

### 3. SFT

- `data/training/sft.jsonl` (133k examples: define/translate tasks).
- Add general instruction data (English/Hindi) so the model stays a usable
  assistant — translation-only SFT produces a translator, not an LLM.
- The define-task data doubles as grounding for dictionary-style questions.

### 4. Synthetic data flywheel (the real unlock)

20M tokens is the floor, not the ceiling:

- Use NLLB-200 (which supports bho_Deva) or the CPT model itself to translate
  Hindi corpora → Bhojpuri; filter with round-trip agreement + the
  trained LID classifier (`pipeline/train_lid.py`: 5-way
  Hindi/Braj/Awadhi/Bhojpuri/Magahi on VarDial 2018, 87.9% test accuracy —
  see `data/lid/REPORT.md`; `pipeline/filter_lid.py` applies it).
- Native speakers correcting synthetic text through the dictpress submission
  queue is far cheaper than authoring from scratch — that's the
  dictionary ↔ LLM loop paying for itself.

### 5. Evaluate honestly

See `eval/README.md`. FLORES-200 and the NLLB-MD test splits are the
benchmark; nothing named EVAL-ONLY goes into training. Also track
"is the output actually Bhojpuri or just Hindi" — models regress to Hindi
constantly; the marker-word audit gives a cheap signal.

## License ledger for model training

| bundle | usable for |
|---|---|
| `sft.jsonl`, `mono/all-dedup.txt` | anything incl. commercial (CC-BY/CC-BY-SA/ODC-BY/CC0/Apache mix — attribution + share-alike obligations apply to redistribution of the *data*) |
| `sft-nc.jsonl`, `*-NC.*` files | research / non-commercial only (BHLTR is CC-BY-NC-SA) |
| `*EVAL-ONLY*` | evaluation only, by project policy |

(Web-crawl-derived text — HPLT, MADLAD, NLLB-mined — carries the usual
underlying-copyright caveats of all crawl corpora; the compilations are
openly licensed but the source texts were not individually cleared. Standard
practice for LLM training data; know your jurisdiction.)
