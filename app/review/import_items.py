#!/usr/bin/env python3
"""Load canonical JSONL into the review database as merged headwords.

Idempotent: run after every `make data` so the review app always shows what
the dictionary shows. Items with an accepted-but-unexported edit are left
alone (only their frequency is refreshed) so nothing is lost; run
apply_verdicts.py first to flush those.

A word that leaves canonical is tombstoned `deleted`, and a word that comes
back is opened again — a data rebuild that drops a word by mistake would
otherwise hide it from reviewers for good, even once it returned.

Usage:
    python3 app/review/import_items.py [canonical.jsonl ...]
(default: the same file list `make data` uses, in the same priority order)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db            # noqa: E402
import content       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical"
DEFAULT_FILES = ["wiktionary-bho", "wiktionary-translations-bho", "gatitos-bho",
                 "hindi-cognates-bho", "aligned-bho", "langlinks-bho", "community-bho"]
FREQ = ROOT / "data" / "corpus" / "word-freq.json"
# The corpus is not in git, so the server has no word-freq.json. Fall back to the
# committed headwords-only copy (same one to_dictpress.py ranks the site with) —
# without it every item imports at freq 0 and batches lose frequency ordering.
HEADWORD_FREQ = ROOT / "dictpress" / "headword-freq.json"


def load_freq() -> dict[str, int]:
    for path in (FREQ, HEADWORD_FREQ):
        if path.exists():
            return json.loads(path.read_text())
    return {}


def review_deleted(con, row) -> bool:
    """Did reviewers delete this word, as opposed to a data rebuild dropping it?"""
    if row["n_incorrect"] >= db.DELETE_VOTES:
        return True
    return con.execute("SELECT 1 FROM decisions WHERE item_id=? AND action='delete'",
                       (row["id"],)).fetchone() is not None


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or [CANON / f"{f}.jsonl" for f in DEFAULT_FILES]
    freq = load_freq()

    by_word: dict[str, list[tuple[str, dict]]] = {}
    for path in paths:
        if not path.exists():
            print(f"  skip {path.name} (missing)", file=sys.stderr)
            continue
        with path.open() as fh:
            for line in fh:
                if line.strip():
                    e = json.loads(line)
                    by_word.setdefault(e["word"], []).append((path.stem, e))

    db.migrate()
    stats = {"new": 0, "updated": 0, "kept": 0, "gone": 0, "restored": 0}
    with db.tx() as con:
        existing = {r["word"]: r for r in con.execute(
            "SELECT id, word, original, content, status, n_incorrect FROM items")}
        for word, entries in by_word.items():
            merged = content.merge(word, entries)
            blob = json.dumps(merged, ensure_ascii=False)
            f = int(freq.get(word, 0))
            row = existing.get(word)
            if row is None:
                con.execute("INSERT INTO items(word, freq, original, content) VALUES(?,?,?,?)",
                            (word, f, blob, blob))
                stats["new"] += 1
            elif row["original"] == row["content"]:
                # no unexported local change → mirror canonical
                con.execute("UPDATE items SET freq=?, original=?, content=?, exported_content=? WHERE id=?",
                            (f, blob, blob, blob, row["id"]))
                stats["updated"] += 1
            else:
                con.execute("UPDATE items SET freq=? WHERE id=?", (f, row["id"]))
                stats["kept"] += 1
            # Back in canonical: undo a tombstone, but never a review verdict.
            if row["status"] == "deleted" and not review_deleted(con, row):
                con.execute("UPDATE items SET status='open', exported_status=NULL WHERE id=?",
                            (row["id"],))
                stats["restored"] += 1
        # words removed from canonical outside the review flow
        for word, row in existing.items():
            if word not in by_word and row["status"] != "deleted" and not json.loads(row["original"]).get("new"):
                con.execute("UPDATE items SET status='deleted', exported_status='deleted' WHERE id=?", (row["id"],))
                stats["gone"] += 1
    print(f"{len(by_word)} headwords → {stats} → {db.DB_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
