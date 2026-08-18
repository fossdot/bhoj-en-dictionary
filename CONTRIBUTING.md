# Contributing to भोज

Three ways to add Bhojpuri words. All of them end up in the same place.

## 1. On the website — easiest, no account

Open **/submit**, fill in the word and its meaning, press *Submit for review*.
A maintainer approves it and it goes live. The page has a short guide built in.

No Devanagari keyboard? The form links to the
[Lexilogos Bhojpuri keyboard](https://www.lexilogos.com/keyboard/bhojpuri.htm) —
type the word there, then copy it across.

If the word is already in the dictionary, open its entry and use the ✏️
*Suggest an edit* icon instead of adding a duplicate.

## 2. Open a GitHub issue — no coding

Use the **[Add a Bhojpuri word](../../issues/new?template=add-word.yml)** issue
form: word, meanings, optionally pronunciation, an example sentence, and your
region. A maintainer converts it into an entry.

## 3. Send a pull request — for anything larger

Words live as JSONL — one entry per line — in `data/canonical/`.
Community contributions go in **`data/canonical/community-bho.jsonl`**:

```json
{"word": "मड़ई", "lang": "bho", "script": "Deva", "translit": ["maṛaī"],
 "phones": [], "tags": [],
 "senses": [{"pos": "noun", "gloss": "thatched hut", "examples":
   [{"bho": "ऊ मड़ई में रहेला", "en": "he lives in a thatched hut"}]}],
 "source": "community submission", "source_url": "", "license": "CC BY-SA 4.0"}
```

Before pushing:

```sh
python3 pipeline/validate_canonical.py   # CI runs this on every PR
```

Rebuild the site from the data with `make data dict`.

### What makes a good entry

- Dictionary form, not an inflected one — मड़ई, not मड़इया
- One meaning per sense, in short plain English
- Note the region when usage is local: `"tags": ["region:Ballia"]`
- **Words Hindi doesn't have are the most valuable** — those are why this
  dictionary exists
- **Example sentences are the single most valuable field.** They feed both the
  dictionary and the Bhojpuri language-model training data, and almost no
  existing source has them.

Don't guess at meanings you're unsure of — say so in the PR instead. An unsure
word we can check beats a wrong entry, and beats never learning the word exists.

### Highest-leverage task right now

2,882 machine-mined candidates sit in `data/canonical/*-review.jsonl`,
deliberately excluded from the dictionary because their confidence was
borderline. Promoting the good ones and deleting the wrong ones grows the
dictionary faster than any scraper. A native speaker skimming a few hundred
lines is worth more than a week of mining.

## For maintainers

Website submissions live only in `dictpress/data.db` until exported. Export
approved ones into `community-bho.jsonl` **before** running `make dict`, which
rebuilds the database from the canonical files and would otherwise discard them.
