# Contributing to भोज

Illustrated step-by-step guide (with screenshots of every step):
see the contributor's guide artifact, or follow the short version below.

## On the website (no account needed)

1. **Search first.** If the word exists, use the ✏️ *Suggest an edit* icon on
   its entry instead of re-adding it.
2. **Suggest new entry** (footer link, every page): word in Devanagari in
   dictionary form, optional romanization, one meaning per definition box
   (language: English, pick the part of speech). `+ Add another definition`
   per extra sense.
3. Submit — everything queues for moderator review at `/admin/pending`;
   nothing publishes unreviewed.

What reviewers look for: lemma not inflected form, Devanagari headwords,
short plain English glosses, region noted when usage is local. Regional
variants and words Hindi doesn't have are the most wanted. Unsure spelling
is fine — say so and submit anyway.

## Through the repo

Entries live as JSONL in `data/canonical/` (see README for the schema).
Hand-curated community words go in `data/canonical/community-bho.jsonl` —
usage examples (`examples: [{"bho": …, "en": …}]`) are the most valuable
field; they feed both the dictionary and the LLM training data.

```sh
make data dict   # regenerate import CSV, rebuild DB, restart the site
```

**Highest-leverage task:** review the 2,882 borderline machine-mined
candidates in `data/canonical/*-review.jsonl` — promote good ones into the
main files, delete wrong ones.

## For moderators

Approved website submissions live only in `dictpress/data.db`. Export them
into `community-bho.jsonl` before running `make dict`, which rebuilds the DB
from the canonical files and would otherwise discard them.
