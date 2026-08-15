# Evaluation protocol

The point of keeping FLORES-200 out of all training data is so these numbers
mean something. Do not train on anything named `EVAL-ONLY`.

## Benchmarks

| set | file | use |
|---|---|---|
| FLORES-200 dev (997) | `data/corpus/parallel/flores200-dev-EVAL-ONLY.jsonl` | validation during training |
| FLORES-200 devtest (1,012) | `data/corpus/parallel/flores200-devtest-EVAL-ONLY.jsonl` | final test — report this |

Both directions matter: en→bho (generation quality in Bhojpuri) and bho→en
(comprehension). Score with chrF2 — BLEU under-rewards morphologically rich
Devanagari text.

```sh
# model produces one hypothesis per line, aligned with the reference file
python3 eval/score.py --hyp my-model.bho.txt \
    --ref data/corpus/parallel/flores200-devtest-EVAL-ONLY.jsonl --field bho
```

`eval/score.py` is a dependency-free chrF2 for progress tracking; use
[sacrebleu](https://github.com/mjpost/sacrebleu) for publishable numbers.

## Reference points (NLLB paper, bho_Deva devtest, chrF2)

- NLLB-200 dense 3.3B: ~46 (en→bho), for orientation only — verify against
  current leaderboards before citing.

## Also worth building (future)

- Word-translation accuracy on a held-out slice of `data/training/lexicon.tsv`
- Bhojpuri-vs-Hindi discrimination test (models love to answer in Hindi —
  measure Devanagari output that is actually Bhojpuri, e.g. by checking
  bho-specific function words बा/बाड़े/बानी/के/खातिर frequency)
- Perplexity on a held-out slice of `mono/all-dedup.txt`
