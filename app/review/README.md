# भोज review — batch verification app

Reviewers (students in the Hikmat Foundation *school to livelihood* programme,
or anyone the maintainers invite) verify dictionary entries 100 at a time.
Verdicts are combined into decisions and written back into `data/canonical/`,
so the review app never becomes a second source of truth.

## Rules

The programme runs in two phases. The quorum is a setting, not code.

**Phase 1 — coverage (default, `REVIEW_VERIFY_VOTES=1`).** The goal is that every
entry is looked at once. Two students never get the same word.

| Verdict                | Result                                                         |
|------------------------|----------------------------------------------------------------|
| Correct                | `verified` tag → badge on the dictionary site                  |
| Incorrect              | stays open with one vote; the *next* batch serves it first, so a second student sees it (`REVIEW_DELETE_VOTES=2`). Two Incorrect → deleted; Incorrect then Correct → teacher decides |
| Edit                   | a teacher accepts / amends / rejects                           |

In phase 1 a student sees only their own batch and their own history. The
*Others* tab, contribution pages, and any mention of teachers are hidden from
students (`REVIEW_PHASE=1`); the maintainer account still has the teacher pages.

**Phase 2 — cross-review (later).** When everything has been seen once, set
`REVIEW_VERIFY_VOTES=2 REVIEW_PHASE=2` and run `python3 app/review/app.py reopen-cross-review`.
Every once-verified word goes back into the queue for a second, independent
opinion. Agreement keeps the tag; disagreement goes to a teacher.

Batches prefer words that already have a vote (so decisions close), then the
most frequent words in the corpus. A word is never served twice to the same
person, and unfinished batches stop reserving words after 7 days.

**Independence:** the *Others* tab lists everyone's verdicts, but a word that is
still waiting unjudged in *your* batch is hidden from you until you decide it.

## Run locally

```sh
make review-import                                   # canonical → app/review/review.db
.venv/bin/python app/review/app.py create-teacher vishal "Vishal Arya"
make review-run                                      # http://localhost:9100
```

The first account to register also becomes a teacher, so a fresh install can be
bootstrapped from the browser instead. Students register with the invite code
(`REVIEW_INVITE_CODE`, default `bhoj`); teachers can also create accounts and
reset passwords under *Teacher → Accounts*.

## Publish decisions

```sh
make review-apply
```

runs `apply_verdicts.py` (decisions → `data/cleaning/review-findings-*.jsonl` →
`pipeline/apply_findings.py` → canonical files, log in `review-applied-*.jsonl`),
then validates, rebuilds the dictionary, and re-imports so the app shows the
new state. Commit the canonical changes and the cleaning logs afterwards.
`apply_verdicts.py --dry-run` only writes the findings file.

## Deploy (same VPS as the dictionary)

```sh
docker build -t bhoj-review app/review
docker run -d --name bhoj-review --restart unless-stopped -p 127.0.0.1:9100:9100 \
  -v /srv/bhoj/review:/data \
  -e REVIEW_INVITE_CODE=<class-code> -e DICT_URL=https://bhoj.example.org \
  bhoj-review
```

Put it behind the same Caddy/nginx as dictpress (for example `review.bhoj.example.org`
or `/review/`). `/data/review.db` is the only state — back it up nightly with the
dictpress `data.db`. To refresh items after a data rebuild, run `import_items.py`
against the mounted database:

```sh
REVIEW_DB=/srv/bhoj/review/review.db .venv/bin/python app/review/import_items.py
```

Environment: `REVIEW_DB`, `REVIEW_SECRET_KEY` (generated and stored on first run
if unset), `REVIEW_INVITE_CODE`, `REVIEW_BATCH_SIZE` (100), `REVIEW_PHASE` (1),
`REVIEW_VERIFY_VOTES` (1), `REVIEW_DELETE_VOTES` (2), `DICT_URL`.

## Files

- `app.py` — Flask routes (students: `/`, `/verify`, `/my-work`; teachers also `/students-work`, `/dashboard`)
- `db.py` — SQLite schema, consensus rules, batch assignment
- `content.py` — merge canonical entries into one headword, diff, and turn edits into findings
- `import_items.py` — canonical → review.db (idempotent)
- `apply_verdicts.py` — review.db → canonical via `pipeline/apply_findings.py`
