#!/usr/bin/env python3
"""Pull public suggestions from the dictionary site into the review queue.

dictpress stores two kinds of public input in its SQLite database:
  * comments   — free text attached to a definition ("suggest an edit" / comments box)
  * pending entries — new words suggested through /submit, with their definitions

Both become 'edit' verdicts by a pseudo-user "public" in the review app, so a
teacher handles them under Students' Work → Review exactly like student edits:
  * a comment on an existing word  → edit verdict whose note is the comment; the
    teacher amends the entry (or rejects)
  * a new word                     → a new review item flagged "new"; accepting
    it puts it in the student queue, and once verified apply_verdicts.py appends
    it to data/canonical/community-bho.jsonl

Each dictpress row is imported once (tracked in review.db, nothing is deleted
from the dictionary database). Safe to run any time; deploy/setup.sh runs it
before rebuilding the dictionary database so nothing is lost.

Usage:
    python3 app/review/import_public.py --dict-db dictpress/data.db
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

PUBLIC_USERNAME = "public"
PUBLIC_NAME = "Public (dictionary site)"


def public_user_id() -> int:
    u = db.get_user(username=PUBLIC_USERNAME)
    if u:
        return u["id"]
    # unusable password: nobody logs in as "public"
    import secrets
    return db.create_user(PUBLIC_USERNAME, PUBLIC_NAME, secrets.token_hex(32), "student")


def already(con, kind: str, source_id: str) -> bool:
    return con.execute("SELECT 1 FROM public_imports WHERE kind=? AND source_id=?", (kind, source_id)).fetchone() is not None


def upsert_public_edit(con, item_id: int, uid: int, reason: str, proposed: dict) -> None:
    """One public verdict per item; new comments are appended and the edit reopened."""
    v = con.execute("SELECT id, reason, decision FROM verdicts WHERE item_id=? AND user_id=?", (item_id, uid)).fetchone()
    if v:
        con.execute("UPDATE verdicts SET reason=?, decision=NULL, proposed=?, created_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                    ((v["reason"] + "\n\n" + reason).strip(), json.dumps(proposed, ensure_ascii=False), v["id"]))
    else:
        con.execute("INSERT INTO verdicts(item_id, user_id, verdict, reason, proposed) VALUES(?,?,'edit',?,?)",
                    (item_id, uid, reason, json.dumps(proposed, ensure_ascii=False)))
    con.execute("UPDATE items SET status='edit_pending', updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                "WHERE id=? AND status NOT IN ('deleted')", (item_id,))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dict-db", required=True, type=Path, help="dictpress data.db")
    args = ap.parse_args()
    if not args.dict_db.exists():
        sys.exit(f"{args.dict_db} not found")

    db.migrate()
    src = sqlite3.connect(f"file:{args.dict_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    uid = public_user_id()
    stats = {"comments": 0, "new_words": 0, "skipped": 0}

    with db.tx() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS public_imports (
            kind TEXT NOT NULL, source_id TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            PRIMARY KEY (kind, source_id))""")

        # --- comments on existing definitions
        rows = src.execute("""
            SELECT c.id, c.comments, c.created_at, e.content AS word_json, d.content AS def_json
            FROM comments c JOIN entries e ON e.id = c.from_id
            LEFT JOIN entries d ON d.id = c.to_id ORDER BY c.id""").fetchall()
        for r in rows:
            if already(con, "comment", str(r["id"])):
                continue
            word = json.loads(r["word_json"])[0]
            definition = json.loads(r["def_json"])[0] if r["def_json"] else ""
            it = con.execute("SELECT id, content FROM items WHERE word=?", (word,)).fetchone()
            if not it:
                stats["skipped"] += 1
                con.execute("INSERT INTO public_imports(kind, source_id) VALUES('comment', ?)", (str(r["id"]),))
                continue
            note = f"Public comment{' on “' + definition + '”' if definition else ''} ({r['created_at'][:10]}): {r['comments'].strip()}"
            upsert_public_edit(con, it["id"], uid, note, json.loads(it["content"]))
            con.execute("INSERT INTO public_imports(kind, source_id) VALUES('comment', ?)", (str(r["id"]),))
            stats["comments"] += 1

        # --- new words suggested via /submit (pending entries + their definitions)
        rows = src.execute("""
            SELECT e.id, e.guid, e.content, e.phones, e.notes, e.created_at FROM entries e
            WHERE e.status='pending' AND e.lang='bhojpuri' ORDER BY e.id""").fetchall()
        for r in rows:
            if already(con, "submission", r["guid"]):
                continue
            word = json.loads(r["content"])[0].strip()
            defs = src.execute("""
                SELECT d.content, d.notes, rel.types FROM relations rel JOIN entries d ON d.id = rel.to_id
                WHERE rel.from_id=? ORDER BY rel.id""", (r["id"],)).fetchall()
            senses = []
            for d in defs:
                gloss = json.loads(d["content"])[0].strip()
                types = json.loads(d["types"] or "[]")
                if gloss:
                    senses.append({"pos": types[0] if types else "", "gloss": gloss, "examples": [], "origins": []})
            if not word:
                stats["skipped"] += 1
                con.execute("INSERT INTO public_imports(kind, source_id) VALUES('submission', ?)", (r["guid"],))
                continue
            note = f"New word suggested on the dictionary site ({r['created_at'][:10]})."
            if not senses:
                note += " No meaning was given — add one below, or reject."
            if r["notes"]:
                note += f" Note: {r['notes'].strip()}"
            existing = con.execute("SELECT id, content FROM items WHERE word=?", (word,)).fetchone()
            if existing:
                # word already in the dictionary: treat as a comment proposing extra meanings
                cur = json.loads(existing["content"])
                have = {s["gloss"].lower() for s in cur["senses"]}
                proposed = {**cur, "senses": cur["senses"] + [s for s in senses if s["gloss"].lower() not in have]}
                upsert_public_edit(con, existing["id"], uid, note + " (word already exists — proposed meanings added)", proposed)
            else:
                content = {"word": word, "translit": json.loads(r["phones"] or "[]"), "tags": ["src:public"],
                           "sources": ["community-bho"], "senses": senses, "new": True}
                blob = json.dumps(content, ensure_ascii=False)
                cur = con.execute("INSERT INTO items(word, freq, original, content, status) VALUES(?, 0, ?, ?, 'edit_pending')",
                                  (word, blob, blob))
                con.execute("INSERT INTO verdicts(item_id, user_id, verdict, reason, proposed) VALUES(?,?,'edit',?,?)",
                            (cur.lastrowid, uid, note, blob))
            con.execute("INSERT INTO public_imports(kind, source_id) VALUES('submission', ?)", (r["guid"],))
            stats["new_words"] += 1
    print(f"public input → review queue: {stats}", file=sys.stderr)


if __name__ == "__main__":
    main()
