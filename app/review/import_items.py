#!/usr/bin/env python3
"""Load canonical JSONL into the review database as merged headwords.

Idempotent: run after every `make data` so the review app always shows what
the dictionary shows. Items with an accepted-but-unexported edit are left
alone (only their frequency is refreshed) so nothing is lost; run
apply_verdicts.py first to flush those.

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


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or [CANON / f"{f}.jsonl" for f in DEFAULT_FILES]
    freq = json.loads(FREQ.read_text()) if FREQ.exists() else {}

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
    stats = {"new": 0, "updated": 0, "kept": 0, "gone": 0}
    with db.tx() as con:
        existing = {r["word"]: r for r in con.execute(
            "SELECT id, word, original, content, status FROM items")}
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
        # words removed from canonical outside the review flow
        for word, row in existing.items():
            if word not in by_word and row["status"] != "deleted":
                con.execute("UPDATE items SET status='deleted', exported_status='deleted' WHERE id=?", (row["id"],))
                stats["gone"] += 1
    print(f"{len(by_word)} headwords → {stats} → {db.DB_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
