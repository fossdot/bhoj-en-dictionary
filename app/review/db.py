"""SQLite layer for the review app.

One file, no ORM. Every function takes/returns plain dicts. The schema is
created on first use; `migrate()` is idempotent so it can run at every start.
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("REVIEW_DB", HERE / "review.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'student' CHECK(role IN ('student', 'teacher')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- One row per merged headword (same merge the dictionary site shows).
--   original: content as imported from canonical (used to diff accepted edits)
--   content:  current content (accepted edits applied here first)
--   exported_*: what has been written back to canonical so far
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word TEXT NOT NULL UNIQUE,
  freq INTEGER NOT NULL DEFAULT 0,
  original TEXT NOT NULL,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open', 'verified', 'deleted', 'conflict', 'edit_pending')),
  n_correct INTEGER NOT NULL DEFAULT 0,
  n_incorrect INTEGER NOT NULL DEFAULT 0,
  exported_content TEXT,
  exported_status TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_items_status_freq ON items(status, freq DESC);

CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_batches_user ON batches(user_id, completed_at);

CREATE TABLE IF NOT EXISTS batch_items (
  batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES items(id),
  position INTEGER NOT NULL,
  PRIMARY KEY (batch_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_batch_items_item ON batch_items(item_id);

CREATE TABLE IF NOT EXISTS verdicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES items(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  batch_id INTEGER REFERENCES batches(id),
  verdict TEXT NOT NULL CHECK(verdict IN ('correct', 'incorrect', 'edit')),
  reason TEXT NOT NULL DEFAULT '',
  proposed TEXT,                       -- JSON content for 'edit'
  decision TEXT CHECK(decision IN ('accepted', 'rejected')),  -- teacher, for 'edit'
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  UNIQUE (item_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_verdicts_user ON verdicts(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_verdicts_created ON verdicts(created_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES items(id),
  verdict_id INTEGER REFERENCES verdicts(id),
  teacher_id INTEGER NOT NULL REFERENCES users(id),
  action TEXT NOT NULL CHECK(action IN ('accept_edit', 'reject_edit', 'keep', 'delete')),
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_decisions_item ON decisions(item_id);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# Phase 1 (coverage): one reviewer's "Correct" verifies, so every entry gets seen
# once as fast as possible. A single "Incorrect" does NOT delete: the word stays
# open with one vote and batch assignment sends it to the next reviewer first, so
# a regional word is never lost on one student's opinion.
# Phase 2 (cross-review, later): set REVIEW_VERIFY_VOTES=2 and run
#   python3 app/review/app.py reopen-cross-review
# which puts every once-verified word back in the queue for a second opinion.
VERIFY_VOTES = int(os.environ.get("REVIEW_VERIFY_VOTES", "1"))   # 'correct' verdicts to verify
DELETE_VOTES = int(os.environ.get("REVIEW_DELETE_VOTES", "2"))   # 'incorrect' verdicts to delete
BATCH_TTL_DAYS = 7        # an unfinished batch stops reserving items after this


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


@contextmanager
def tx():
    """A connection with an explicit transaction; commits on success."""
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def migrate() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = connect()
    con.executescript(SCHEMA)
    con.close()


def setting(key: str, default: str | None = None) -> str | None:
    con = connect()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    con = connect()
    con.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    con.close()


def secret_key() -> str:
    """Flask session key: from the environment, else generated once and stored."""
    env = os.environ.get("REVIEW_SECRET_KEY")
    if env:
        return env
    key = setting("secret_key")
    if not key:
        key = secrets.token_hex(32)
        set_setting("secret_key", key)
    return key


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# -------------------------------------------------------------------- users

def create_user(username: str, name: str, password: str, role: str = "student") -> int:
    with tx() as con:
        cur = con.execute(
            "INSERT INTO users(username, name, password_hash, role) VALUES(?,?,?,?)",
            (username.strip().lower(), name.strip(), hash_password(password), role))
        return cur.lastrowid


def get_user(user_id: int | None = None, username: str | None = None) -> dict | None:
    con = connect()
    if user_id is not None:
        row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    else:
        row = con.execute("SELECT * FROM users WHERE username=?", ((username or "").strip().lower(),)).fetchone()
    con.close()
    return dict(row) if row else None


def count_users() -> int:
    con = connect()
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    return n


def list_users() -> list[dict]:
    con = connect()
    rows = con.execute("""
        SELECT u.*, COUNT(v.id) AS n_verdicts,
               SUM(v.verdict='edit' AND v.decision='accepted') AS n_accepted
        FROM users u LEFT JOIN verdicts v ON v.user_id = u.id
        GROUP BY u.id ORDER BY n_verdicts DESC, u.name""").fetchall()
    con.close()
    return [dict(r) for r in rows]


def set_password(user_id: int, password: str) -> None:
    with tx() as con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))


def set_role(user_id: int, role: str) -> None:
    with tx() as con:
        con.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))


# -------------------------------------------------------------------- items

def item(item_id: int) -> dict | None:
    con = connect()
    row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    con.close()
    return _item(row)


def _item(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    d["content"] = json.loads(d["content"])
    d["original"] = json.loads(d["original"])
    return d


def item_stats() -> dict:
    con = connect()
    rows = con.execute("SELECT status, COUNT(*) n FROM items GROUP BY status").fetchall()
    total_verdicts = con.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
    reviewers = con.execute("SELECT COUNT(DISTINCT user_id) FROM verdicts").fetchone()[0]
    reviewed_once = con.execute("SELECT COUNT(*) FROM items WHERE n_correct + n_incorrect > 0 "
                                "OR status IN ('verified','deleted','edit_pending','conflict')").fetchone()[0]
    con.close()
    stats = {r["status"]: r["n"] for r in rows}
    stats["total"] = sum(stats.values())
    stats["reviewed_once"] = reviewed_once
    stats["quorum"] = VERIFY_VOTES
    stats["verdicts"] = total_verdicts
    stats["reviewers"] = reviewers
    return stats


# ------------------------------------------------------------------ batches

def active_batch(user_id: int) -> dict | None:
    """The user's current unfinished batch with its remaining items, if any."""
    con = connect()
    b = con.execute(
        "SELECT * FROM batches WHERE user_id=? AND completed_at IS NULL ORDER BY id DESC LIMIT 1",
        (user_id,)).fetchone()
    if not b:
        con.close()
        return None
    total = con.execute("SELECT COUNT(*) FROM batch_items WHERE batch_id=?", (b["id"],)).fetchone()[0]
    done = con.execute("""
        SELECT COUNT(*) FROM batch_items bi
        JOIN verdicts v ON v.item_id = bi.item_id AND v.user_id = ?
        WHERE bi.batch_id = ?""", (user_id, b["id"])).fetchone()[0]
    con.close()
    return {**dict(b), "total": total, "done": done}


def next_in_batch(user_id: int, batch_id: int) -> dict | None:
    """First item in the batch this user hasn't judged and that is still open."""
    con = connect()
    row = con.execute("""
        SELECT i.* FROM batch_items bi JOIN items i ON i.id = bi.item_id
        WHERE bi.batch_id = ?
          AND i.status IN ('open', 'conflict')
          AND NOT EXISTS (SELECT 1 FROM verdicts v WHERE v.item_id = i.id AND v.user_id = ?)
        ORDER BY bi.position LIMIT 1""", (batch_id, user_id)).fetchone()
    con.close()
    return _item(row)


def create_batch(user_id: int, size: int) -> dict | None:
    """Reserve up to `size` open items for this user.

    Preference order: items that already have one verdict from someone else
    (finishing them yields a decision), then untouched items; within each
    group the most frequent words first. Items already judged by this user
    are skipped, and so are items that already have enough reviewers (votes
    plus reservations in other people's active batches) to reach a decision:
    VERIFY_VOTES for an untouched word, DELETE_VOTES once someone said
    "incorrect". In phase 1 (quorum 1) this makes batches disjoint.
    """
    with tx() as con:
        con.execute("UPDATE batches SET completed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                    "WHERE user_id=? AND completed_at IS NULL", (user_id,))
        rows = con.execute(f"""
            WITH reserved AS (
              SELECT bi.item_id, COUNT(*) n FROM batch_items bi
              JOIN batches b ON b.id = bi.batch_id
              WHERE b.completed_at IS NULL
                AND b.created_at > strftime('%Y-%m-%dT%H:%M:%SZ','now','-{BATCH_TTL_DAYS} days')
                AND b.user_id != ?
                AND NOT EXISTS (SELECT 1 FROM verdicts v WHERE v.item_id = bi.item_id AND v.user_id = b.user_id)
              GROUP BY bi.item_id)
            SELECT i.id, (i.n_correct + i.n_incorrect) AS votes
            FROM items i LEFT JOIN reserved r ON r.item_id = i.id
            WHERE i.status = 'open'
              AND NOT EXISTS (SELECT 1 FROM verdicts v WHERE v.item_id = i.id AND v.user_id = ?)
              AND (i.n_correct + i.n_incorrect + COALESCE(r.n, 0))
                  < CASE WHEN i.n_incorrect > 0 THEN {DELETE_VOTES} ELSE {VERIFY_VOTES} END
            ORDER BY votes DESC, i.freq DESC, LENGTH(i.word), i.word
            LIMIT ?""", (user_id, user_id, size)).fetchall()
        if not rows:
            return None
        cur = con.execute("INSERT INTO batches(user_id) VALUES(?)", (user_id,))
        bid = cur.lastrowid
        con.executemany("INSERT INTO batch_items(batch_id, item_id, position) VALUES(?,?,?)",
                        [(bid, r["id"], pos) for pos, r in enumerate(rows)])
    return active_batch(user_id)


def finish_batch(user_id: int, batch_id: int) -> None:
    with tx() as con:
        con.execute("UPDATE batches SET completed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                    "WHERE id=? AND user_id=?", (batch_id, user_id))


def in_active_batch_unjudged(user_id: int, item_id: int) -> bool:
    """True when the item is in the user's open batch and they haven't judged it."""
    con = connect()
    row = con.execute("""
        SELECT 1 FROM batch_items bi JOIN batches b ON b.id = bi.batch_id
        WHERE b.user_id=? AND b.completed_at IS NULL AND bi.item_id=?
          AND NOT EXISTS (SELECT 1 FROM verdicts v WHERE v.item_id=? AND v.user_id=?)""",
        (user_id, item_id, item_id, user_id)).fetchone()
    con.close()
    return row is not None


# ----------------------------------------------------------------- verdicts

def record_verdict(item_id: int, user_id: int, batch_id: int | None, verdict: str,
                   reason: str = "", proposed: dict | None = None) -> str:
    """Insert a verdict and apply the consensus rules. Returns the new item status."""
    with tx() as con:
        it = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not it:
            raise ValueError("no such item")
        if it["status"] in ("verified", "deleted"):
            raise ValueError("item already decided")
        con.execute("""INSERT INTO verdicts(item_id, user_id, batch_id, verdict, reason, proposed)
                       VALUES(?,?,?,?,?,?)""",
                    (item_id, user_id, batch_id, verdict, reason.strip(),
                     json.dumps(proposed, ensure_ascii=False) if proposed else None))
        n_c, n_i, status = it["n_correct"], it["n_incorrect"], it["status"]
        if verdict == "correct":
            n_c += 1
        elif verdict == "incorrect":
            n_i += 1
        if verdict == "edit":
            status = "edit_pending"
        elif n_c > 0 and n_i > 0:
            status = "conflict"
        elif n_c >= VERIFY_VOTES:
            status = "verified"
        elif n_i >= DELETE_VOTES:
            status = "deleted"
        else:
            status = "open"
        con.execute("""UPDATE items SET n_correct=?, n_incorrect=?, status=?,
                       updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?""",
                    (n_c, n_i, status, item_id))
    return status


def last_undoable(user_id: int, batch_id: int) -> dict | None:
    """The user's most recent verdict in this batch, if it can still be taken back
    (the item has not been published since, and no teacher has acted on it)."""
    con = connect()
    row = con.execute("""
        SELECT v.id, v.verdict, i.word FROM verdicts v JOIN items i ON i.id = v.item_id
        WHERE v.user_id=? AND v.batch_id=? AND v.decision IS NULL
          AND COALESCE(i.exported_status, '') != i.status
          AND i.content = COALESCE(i.exported_content, i.original)
          AND NOT EXISTS (SELECT 1 FROM decisions d WHERE d.item_id = i.id AND d.created_at >= v.created_at)
        ORDER BY v.id DESC LIMIT 1""", (user_id, batch_id)).fetchone()
    con.close()
    return dict(row) if row else None


def undo_verdict(verdict_id: int, user_id: int) -> bool:
    """Delete one of the user's own verdicts and recompute the item from what remains."""
    with tx() as con:
        v = con.execute("SELECT * FROM verdicts WHERE id=? AND user_id=? AND decision IS NULL",
                        (verdict_id, user_id)).fetchone()
        if not v:
            return False
        item_id = v["item_id"]
        con.execute("DELETE FROM verdicts WHERE id=?", (verdict_id,))
        r = con.execute("""SELECT SUM(verdict='correct') c, SUM(verdict='incorrect') i,
                                  SUM(verdict='edit' AND decision IS NULL) e
                           FROM verdicts WHERE item_id=?""", (item_id,)).fetchone()
        n_c, n_i, pending = r["c"] or 0, r["i"] or 0, r["e"] or 0
        if pending:
            status = "edit_pending"
        elif n_c and n_i:
            status = "conflict"
        elif n_c >= VERIFY_VOTES:
            status = "verified"
        elif n_i >= DELETE_VOTES:
            status = "deleted"
        else:
            status = "open"
        con.execute("""UPDATE items SET n_correct=?, n_incorrect=?, status=?,
                       updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?""",
                    (n_c, n_i, status, item_id))
        return True


def verdict(verdict_id: int) -> dict | None:
    con = connect()
    row = con.execute("""
        SELECT v.*, u.name AS user_name, u.username, i.word, i.status AS item_status,
               i.content AS item_content, i.original AS item_original
        FROM verdicts v JOIN users u ON u.id = v.user_id JOIN items i ON i.id = v.item_id
        WHERE v.id=?""", (verdict_id,)).fetchone()
    con.close()
    if not row:
        return None
    d = dict(row)
    d["proposed"] = json.loads(d["proposed"]) if d["proposed"] else None
    d["item_content"] = json.loads(d["item_content"])
    d["item_original"] = json.loads(d["item_original"])
    return d


def verdicts_for_item(item_id: int) -> list[dict]:
    con = connect()
    rows = con.execute("""
        SELECT v.*, u.name AS user_name, u.username FROM verdicts v
        JOIN users u ON u.id = v.user_id WHERE v.item_id=? ORDER BY v.created_at""", (item_id,)).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        d["proposed"] = json.loads(d["proposed"]) if d["proposed"] else None
        out.append(d)
    return out


def decisions_for_item(item_id: int) -> list[dict]:
    con = connect()
    rows = con.execute("""
        SELECT d.*, u.name AS teacher_name FROM decisions d
        JOIN users u ON u.id = d.teacher_id WHERE d.item_id=? ORDER BY d.created_at""", (item_id,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_verdicts(exclude_user: int | None = None, only_user: int | None = None,
                  kind: str | None = None, page: int = 1, per_page: int = 50) -> tuple[list[dict], int]:
    where, args = [], []
    if exclude_user is not None:
        where.append("v.user_id != ?"); args.append(exclude_user)
    if only_user is not None:
        where.append("v.user_id = ?"); args.append(only_user)
    if kind:
        where.append("v.verdict = ?"); args.append(kind)
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    con = connect()
    total = con.execute(f"SELECT COUNT(*) FROM verdicts v {sql_where}", args).fetchone()[0]
    rows = con.execute(f"""
        SELECT v.id, v.item_id, v.verdict, v.decision, v.created_at, v.reason,
               u.name AS user_name, u.username, i.word, i.status AS item_status
        FROM verdicts v JOIN users u ON u.id = v.user_id JOIN items i ON i.id = v.item_id
        {sql_where} ORDER BY v.created_at DESC, v.id DESC LIMIT ? OFFSET ?""",
        (*args, per_page, (page - 1) * per_page)).fetchall()
    con.close()
    return [dict(r) for r in rows], total


def user_stats(user_id: int) -> dict:
    con = connect()
    r = con.execute("""
        SELECT COUNT(*) total,
               SUM(verdict='correct') n_correct, SUM(verdict='incorrect') n_incorrect,
               SUM(verdict='edit') n_edit, SUM(verdict='edit' AND decision='accepted') n_accepted,
               SUM(verdict='edit' AND decision='rejected') n_rejected
        FROM verdicts WHERE user_id=?""", (user_id,)).fetchone()
    batches = con.execute("SELECT COUNT(*) FROM batches WHERE user_id=? AND completed_at IS NOT NULL",
                          (user_id,)).fetchone()[0]
    con.close()
    d = {k: (r[k] or 0) for k in r.keys()}
    d["batches"] = batches
    return d


# ------------------------------------------------------------------ teacher

def queue(kind: str, page: int = 1, per_page: int = 50) -> tuple[list[dict], int]:
    """kind: 'edits' (pending edit verdicts) or 'conflicts' (split votes)."""
    con = connect()
    if kind == "edits":
        total = con.execute("SELECT COUNT(*) FROM verdicts WHERE verdict='edit' AND decision IS NULL").fetchone()[0]
        rows = con.execute("""
            SELECT v.id AS verdict_id, v.item_id, v.created_at, v.reason, u.name AS user_name, i.word, i.freq
            FROM verdicts v JOIN users u ON u.id = v.user_id JOIN items i ON i.id = v.item_id
            WHERE v.verdict='edit' AND v.decision IS NULL
            ORDER BY i.freq DESC, v.created_at LIMIT ? OFFSET ?""", (per_page, (page - 1) * per_page)).fetchall()
    else:
        total = con.execute("SELECT COUNT(*) FROM items WHERE status='conflict'").fetchone()[0]
        rows = con.execute("""
            SELECT i.id AS item_id, i.word, i.freq, i.n_correct, i.n_incorrect, i.updated_at AS created_at
            FROM items i WHERE i.status='conflict'
            ORDER BY i.freq DESC LIMIT ? OFFSET ?""", (per_page, (page - 1) * per_page)).fetchall()
    con.close()
    return [dict(r) for r in rows], total


def decide_edit(verdict_id: int, teacher_id: int, accept: bool, note: str = "",
                final_content: dict | None = None) -> None:
    """Teacher accepts (optionally with their own corrections) or rejects an edit.

    Accepting writes the content into the item and counts as one 'correct'
    vote on the new content, so one more student confirmation verifies it.
    """
    with tx() as con:
        v = con.execute("SELECT * FROM verdicts WHERE id=? AND verdict='edit'", (verdict_id,)).fetchone()
        if not v or v["decision"]:
            raise ValueError("edit not pending")
        item_id = v["item_id"]
        con.execute("UPDATE verdicts SET decision=? WHERE id=?",
                    ("accepted" if accept else "rejected", verdict_id))
        con.execute("INSERT INTO decisions(item_id, verdict_id, teacher_id, action, note) VALUES(?,?,?,?,?)",
                    (item_id, verdict_id, teacher_id, "accept_edit" if accept else "reject_edit", note.strip()))
        if accept:
            content = final_content or json.loads(v["proposed"])
            con.execute("""UPDATE items SET content=?, status='open', n_correct=1, n_incorrect=0,
                           updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?""",
                        (json.dumps(content, ensure_ascii=False), item_id))
        else:
            it = con.execute("SELECT n_correct, n_incorrect FROM items WHERE id=?", (item_id,)).fetchone()
            status = "conflict" if it["n_correct"] and it["n_incorrect"] else \
                     "verified" if it["n_correct"] >= VERIFY_VOTES else \
                     "deleted" if it["n_incorrect"] >= DELETE_VOTES else "open"
            # any other pending edit keeps the item in the queue
            other = con.execute("SELECT 1 FROM verdicts WHERE item_id=? AND verdict='edit' AND decision IS NULL",
                                (item_id,)).fetchone()
            if other:
                status = "edit_pending"
            con.execute("UPDATE items SET status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                        (status, item_id))


def decide_conflict(item_id: int, teacher_id: int, keep: bool, note: str = "") -> None:
    with tx() as con:
        con.execute("INSERT INTO decisions(item_id, teacher_id, action, note) VALUES(?,?,?,?)",
                    (item_id, teacher_id, "keep" if keep else "delete", note.strip()))
        con.execute("UPDATE items SET status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                    ("verified" if keep else "deleted", item_id))


def reopen_for_cross_review() -> int:
    """Phase 2: put words verified with fewer than VERIFY_VOTES 'correct' verdicts
    back in the queue. Their 'verified' tag stays on the site until a second
    reviewer disagrees (then a teacher decides)."""
    with tx() as con:
        cur = con.execute("""UPDATE items SET status='open',
                             updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                             WHERE status='verified' AND n_correct < ? AND n_incorrect = 0""", (VERIFY_VOTES,))
        return cur.rowcount


# ------------------------------------------------------------------- export

def items_to_export() -> list[dict]:
    """Items whose status or content hasn't been written back to canonical yet."""
    con = connect()
    rows = con.execute("""
        SELECT * FROM items
        WHERE (status IN ('verified', 'deleted') AND COALESCE(exported_status, '') != status)
           OR (status != 'deleted' AND content != COALESCE(exported_content, original))
        ORDER BY freq DESC""").fetchall()
    con.close()
    return [_item(r) for r in rows]


def mark_exported(item_id: int, status: str, content: dict) -> None:
    """Record that canonical now matches `content`/`status`. Working, original and
    exported copies are all set to it so the next import sees no local change.
    A renamed headword renames the item too (unless that word already exists)."""
    blob = json.dumps(content, ensure_ascii=False)
    with tx() as con:
        con.execute("""UPDATE items SET exported_status=?, exported_content=?, original=?, content=?
                       WHERE id=?""", (status, blob, blob, blob, item_id))
        row = con.execute("SELECT word FROM items WHERE id=?", (item_id,)).fetchone()
        if row and row["word"] != content["word"]:
            clash = con.execute("SELECT 1 FROM items WHERE word=?", (content["word"],)).fetchone()
            if clash:
                print(f"  warning: {row['word']} renamed to {content['word']} but an item with that "
                      f"word already exists; keeping the old item name", file=sys.stderr)
            else:
                con.execute("UPDATE items SET word=? WHERE id=?", (content["word"], item_id))
