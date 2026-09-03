#!/usr/bin/env python3
"""भोज review — students verify dictionary entries in batches of 100.

    python3 app/review/app.py create-teacher <username> "<Full name>"
    python3 app/review/app.py run            # dev server on :9100
    python3 app/review/app.py reopen-cross-review   # phase 2: requeue once-verified words

Production: gunicorn -w 1 --threads 8 -b 0.0.0.0:9100 app:app  (see Dockerfile)

Routes: /verify (batch work), /my-work, /students-work (teachers; students in phase 2),
        /dashboard, /dashboard/accounts, /dashboard/publish

Environment:
    REVIEW_DB            path to review.db          (default app/review/review.db)
    REVIEW_SECRET_KEY    Flask session key          (default: generated once, stored in the db)
    REVIEW_INVITE_CODE   code students need to sign up (default: "bhoj")
    REVIEW_PHASE         1 = coverage: students only review their own batches (default)
                         2 = cross-review: Others tab, contribution pages, teacher queues
    REVIEW_BATCH_SIZE    words per batch            (default 100)
    REVIEW_VERIFY_VOTES  'correct' verdicts needed  (default 1 — coverage phase; 2 for cross-review)
    REVIEW_DELETE_VOTES  'incorrect' verdicts needed (default 2)
    DICT_URL             public dictionary URL, for links (default http://localhost:9000)
"""

import functools
import getpass
import os
import secrets
import sys
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import content   # noqa: E402
import db        # noqa: E402

app = Flask(__name__)
db.migrate()
app.secret_key = db.secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

INVITE_CODE = os.environ.get("REVIEW_INVITE_CODE", "bhoj")
BATCH_SIZE = int(os.environ.get("REVIEW_BATCH_SIZE", "100"))
PHASE = int(os.environ.get("REVIEW_PHASE", "1"))
DICT_URL = os.environ.get("DICT_URL", "http://localhost:9000").rstrip("/")

# Parts of speech, labelled for students who learnt grammar in Hindi, not English:
# (value, Hindi term · English term, Bhojpuri example words)
POS_INFO = [
    ("",             "पता नइखे · not sure",                    "खाली छोड़ दीं"),
    ("noun",         "संज्ञा · noun",                          "घर, माई, पानी"),
    ("propernoun",   "व्यक्तिवाचक संज्ञा · proper noun",         "पटना, गंगा, राम"),
    ("verb",         "क्रिया · verb",                          "खाइल, जाइल, कहल"),
    ("adjective",    "विशेषण · adjective",                     "सुन्नर, बड़, लाल"),
    ("adverb",       "क्रिया-विशेषण · adverb",                  "जल्दी, धीरे, आज"),
    ("pronoun",      "सर्वनाम · pronoun",                       "हम, तू, ऊ, ई"),
    ("conjunction",  "योजक · conjunction",                     "आ, बाकिर, काहेकि"),
    ("postposition", "परसर्ग (कारक चिह्न) · postposition",      "के, में, से, पर"),
    ("preposition",  "पूर्वसर्ग · preposition",                  "बिना, बगैर"),
    ("interjection", "विस्मयादिबोधक · interjection",            "अरे, हाय, वाह"),
    ("numeral",      "संख्या · numeral",                        "एक, दू, तीन, पहिला"),
    ("determiner",   "निर्धारक · determiner",                   "ई, ऊ, कुछ, सब"),
    ("particle",     "निपात · particle",                        "ही, भी, तो, ना"),
    ("classifier",   "वर्गीकारक · classifier",                  "गो (एक गो, दू गो)"),
    ("phrase",       "वाक्यांश · phrase",                       "का हाल बा"),
    ("proverb",      "कहावत · proverb",                        "जेकर लाठी ओकर भईंस"),
    ("suffix",       "प्रत्यय · suffix",                        "-वा, -इया"),
    ("prefix",       "उपसर्ग · prefix",                         "अन-, बे-"),
]
POS_LABEL = {p[0]: p[1] for p in POS_INFO}
POS_SHORT = {p[0]: p[1].split(" · ")[0] for p in POS_INFO}   # Hindi term only, for badges


# ------------------------------------------------------------------ helpers

@app.before_request
def load_user():
    g.user = db.get_user(user_id=session["uid"]) if "uid" in session else None
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST" and request.form.get("csrf") != session.get("csrf"):
        abort(400, "bad form token — reload the page and try again")


@app.context_processor
def inject():
    return {"user": g.user, "csrf": session.get("csrf"), "DICT_URL": DICT_URL,
            "POS_INFO": POS_INFO, "POS_LABEL": POS_LABEL, "POS_SHORT": POS_SHORT,
            "VERIFY_VOTES": db.VERIFY_VOTES, "DELETE_VOTES": db.DELETE_VOTES, "PHASE": PHASE,
            "diff": content.diff,
            "visible_tags": lambda tags: [x for x in (tags or []) if not x.startswith("src:")]}


def login_required(f):
    @functools.wraps(f)
    def w(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w


def teacher_required(f):
    @functools.wraps(f)
    def w(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        if g.user["role"] != "teacher":
            abort(403)
        return f(*a, **kw)
    return w


def phase2_required(f):
    """Pages that show other people's work: students only in phase 2, teachers always."""
    @functools.wraps(f)
    def w(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        if PHASE < 2 and g.user["role"] != "teacher":
            return redirect(url_for("home"))
        return f(*a, **kw)
    return w


def page_arg() -> int:
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


# --------------------------------------------------------------------- auth

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db.get_user(username=request.form.get("username", ""))
        if u and db.check_password(request.form.get("password", ""), u["password_hash"]):
            session.permanent = True
            session["uid"] = u["id"]
            nxt = request.args.get("next") or url_for("home")
            return redirect(nxt if nxt.startswith("/") else url_for("home"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        name = request.form.get("name", "").strip()
        pw = request.form.get("password", "")
        code = request.form.get("invite", "")
        if code != INVITE_CODE:
            flash("Wrong invite code. Ask at school.", "error")
        elif not username.isidentifier() or len(username) < 3:
            flash("Username: at least 3 letters, no spaces.", "error")
        elif not name:
            flash("Please enter your name.", "error")
        elif len(pw) < 6:
            flash("Password must be at least 6 characters.", "error")
        elif db.get_user(username=username):
            flash("That username is taken.", "error")
        else:
            role = "teacher" if db.count_users() == 0 else "student"
            uid = db.create_user(username, name, pw, role)
            session.permanent = True
            session["uid"] = uid
            flash(f"Welcome, {name}!", "ok")
            return redirect(url_for("home"))
    return render_template("register.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------- home

@app.route("/")
@login_required
def home():
    batch = db.active_batch(g.user["id"])
    return render_template("home.html", batch=batch, stats=db.item_stats(),
                           me=db.user_stats(g.user["id"]), batch_size=BATCH_SIZE)


@app.post("/batch/new")
@login_required
def batch_new():
    batch = db.create_batch(g.user["id"], BATCH_SIZE)
    if not batch:
        flash("Nothing left to check right now. Every word has been seen. Thank you!", "ok")
        return redirect(url_for("home"))
    return redirect(url_for("review"))


# ------------------------------------------------------------------- review

@app.route("/verify")
@login_required
def review():
    batch = db.active_batch(g.user["id"])
    if not batch:
        return redirect(url_for("home"))
    it = db.next_in_batch(g.user["id"], batch["id"])
    if not it:
        db.finish_batch(g.user["id"], batch["id"])
        return render_template("batch_done.html", batch=batch, me=db.user_stats(g.user["id"]))
    return render_template("review.html", item=it, batch=batch,
                           undo=db.last_undoable(g.user["id"], batch["id"]))


@app.post("/verify/undo")
@login_required
def undo():
    batch = db.active_batch(g.user["id"])
    last = db.last_undoable(g.user["id"], batch["id"]) if batch else None
    if last and db.undo_verdict(last["id"], g.user["id"]):
        flash(f"Undone. {last['word']} is back in your batch.", "ok")
    return redirect(url_for("review"))


def _guard_item(item_id: int) -> dict:
    it = db.item(item_id)
    if not it:
        abort(404)
    if it["status"] in ("verified", "deleted"):
        flash("That word was already decided while you were looking at it.", "ok")
        abort(redirect(url_for("review")))
    return it


@app.post("/verify/<int:item_id>/answer")
@login_required
def verdict(item_id):
    it = _guard_item(item_id)
    v = request.form.get("verdict")
    if v not in ("correct", "incorrect"):
        abort(400)
    batch = db.active_batch(g.user["id"])
    try:
        db.record_verdict(it["id"], g.user["id"], batch["id"] if batch else None, v,
                          reason=request.form.get("reason", ""))
    except Exception:  # duplicate (double tap) or already decided — just move on
        pass
    return redirect(url_for("review") if batch else url_for("home"))


@app.route("/verify/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit(item_id):
    it = _guard_item(item_id)
    if request.method == "POST":
        proposed = content.from_form(request.form, it["content"])
        if not proposed["senses"]:
            flash("You removed every meaning. Mark the word Incorrect instead.", "error")
            return render_template("edit.html", item=it, base=it["content"], action=request.path)
        if proposed == it["content"] and not request.form.get("reason", "").strip():
            flash("Nothing changed. Change something, or go back and mark it Correct.", "error")
            return render_template("edit.html", item=it, base=it["content"], action=request.path)
        batch = db.active_batch(g.user["id"])
        try:
            db.record_verdict(it["id"], g.user["id"], batch["id"] if batch else None, "edit",
                              reason=request.form.get("reason", ""), proposed=proposed)
        except Exception:
            pass
        flash("Edit saved. It will be checked before it goes into the dictionary.", "ok")
        return redirect(url_for("review") if batch else url_for("home"))
    return render_template("edit.html", item=it, base=it["content"], action=request.path)


# -------------------------------------------------------------- browse work

@app.route("/students-work")
@phase2_required
def others():
    kind = request.args.get("kind") or None
    only = request.args.get("user", type=int)
    rows, total = db.list_verdicts(exclude_user=None if only else g.user["id"], only_user=only,
                                   kind=kind, page=page_arg(), per_page=50)
    ctx = {"pending_edits": [], "pending_conflicts": [], "n_edits": 0, "n_conflicts": 0}
    if g.user["role"] == "teacher":
        ctx["pending_edits"], ctx["n_edits"] = db.queue("edits", per_page=10)
        ctx["pending_conflicts"], ctx["n_conflicts"] = db.queue("conflicts", per_page=10)
    return render_template("others.html", rows=rows, total=total, page=page_arg(), kind=kind,
                           only=only, users=db.list_users(), **ctx)


@app.route("/my-work")
@login_required
def mine():
    rows, total = db.list_verdicts(only_user=g.user["id"], page=page_arg(), per_page=50)
    return render_template("mine.html", rows=rows, total=total, page=page_arg(),
                           me=db.user_stats(g.user["id"]))


@app.route("/students-work/answer/<int:verdict_id>")
@phase2_required
def contrib(verdict_id):
    v = db.verdict(verdict_id)
    if not v:
        abort(404)
    # Independence: if this word is waiting in *my* batch and I haven't judged it,
    # I must not see what others said about it.
    if v["user_id"] != g.user["id"] and db.in_active_batch_unjudged(g.user["id"], v["item_id"]):
        return render_template("blocked.html", word=v["word"])
    return render_template("contrib.html", v=v, verdicts=db.verdicts_for_item(v["item_id"]),
                           decisions=db.decisions_for_item(v["item_id"]), item=db.item(v["item_id"]))


@app.route("/word/<int:item_id>")
@phase2_required
def word(item_id):
    it = db.item(item_id)
    if not it:
        abort(404)
    if db.in_active_batch_unjudged(g.user["id"], item_id):
        return render_template("blocked.html", word=it["word"])
    return render_template("word.html", item=it, verdicts=db.verdicts_for_item(item_id),
                           decisions=db.decisions_for_item(item_id))


# ------------------------------------------------------------------ teacher

@app.route("/dashboard")
@teacher_required
def teacher():
    edits, n_edits = db.queue("edits", per_page=1)
    conflicts, n_conflicts = db.queue("conflicts", per_page=1)
    return render_template("teacher.html", stats=db.item_stats(), n_edits=n_edits,
                           n_conflicts=n_conflicts, n_export=len(db.items_to_export()),
                           users=db.list_users())


@app.route("/students-work/edits")
@teacher_required
def teacher_edits():
    rows, total = db.queue("edits", page=page_arg())
    return render_template("queue.html", kind="edits", rows=rows, total=total, page=page_arg())


@app.route("/students-work/split-votes")
@teacher_required
def teacher_conflicts():
    rows, total = db.queue("conflicts", page=page_arg())
    return render_template("queue.html", kind="conflicts", rows=rows, total=total, page=page_arg())


@app.route("/students-work/edit/<int:verdict_id>", methods=["GET", "POST"])
@teacher_required
def teacher_edit(verdict_id):
    v = db.verdict(verdict_id)
    if not v or v["verdict"] != "edit":
        abort(404)
    it = db.item(v["item_id"])
    if request.method == "POST":
        action = request.form.get("action")
        note = request.form.get("note", "")
        try:
            if action == "reject":
                db.decide_edit(verdict_id, g.user["id"], accept=False, note=note)
                flash("Edit rejected.", "ok")
            elif action == "accept":
                db.decide_edit(verdict_id, g.user["id"], accept=True, note=note)
                flash("Edit accepted — it now needs one more student to confirm.", "ok")
            elif action == "amend":
                final = content.from_form(request.form, v["proposed"])
                if not final["senses"]:
                    flash("Every meaning removed — reject instead, or mark the word incorrect.", "error")
                    return redirect(request.path)
                db.decide_edit(verdict_id, g.user["id"], accept=True, note=note, final_content=final)
                flash("Edit accepted with your corrections.", "ok")
            else:
                abort(400)
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("teacher_edits"))
    return render_template("teacher_edit.html", v=v, item=it, base=v["proposed"],
                           changes=content.diff(it["content"], v["proposed"]),
                           verdicts=db.verdicts_for_item(it["id"]))


@app.post("/students-work/split-votes/<int:item_id>")
@teacher_required
def teacher_conflict(item_id):
    it = db.item(item_id)
    if not it or it["status"] != "conflict":
        abort(404)
    keep = request.form.get("action") == "keep"
    db.decide_conflict(item_id, g.user["id"], keep=keep, note=request.form.get("note", ""))
    flash(("Kept — marked verified." if keep else "Deleted.") + f" ({it['word']})", "ok")
    return redirect(url_for("teacher_conflicts"))


@app.route("/dashboard/accounts", methods=["GET", "POST"])
@teacher_required
def teacher_users():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            username = request.form.get("username", "").strip().lower()
            name = request.form.get("name", "").strip()
            pw = request.form.get("password", "")
            if not username.isidentifier() or not name or len(pw) < 6:
                flash("Need a username (letters/digits), a name, and a 6+ character password.", "error")
            elif db.get_user(username=username):
                flash("Username taken.", "error")
            else:
                db.create_user(username, name, pw, request.form.get("role", "student"))
                flash(f"Created {username}.", "ok")
        elif action == "password":
            pw = request.form.get("password", "")
            if len(pw) < 6:
                flash("Password must be at least 6 characters.", "error")
            else:
                db.set_password(int(request.form["user_id"]), pw)
                flash("Password reset.", "ok")
        elif action == "role":
            uid = int(request.form["user_id"])
            if uid == g.user["id"]:
                flash("You can't change your own role.", "error")
            else:
                db.set_role(uid, request.form.get("role", "student"))
                flash("Role updated.", "ok")
        return redirect(url_for("teacher_users"))
    return render_template("users.html", users=db.list_users(), invite=INVITE_CODE)


@app.route("/dashboard/publish")
@teacher_required
def teacher_export():
    items = db.items_to_export()
    return render_template("export.html", items=items)


# ---------------------------------------------------------------------- CLI

def cli() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "create-teacher":
        if len(sys.argv) < 4:
            sys.exit('usage: app.py create-teacher <username> "<Full name>"')
        pw = getpass.getpass("password: ")
        uid = db.create_user(sys.argv[2], sys.argv[3], pw, "teacher")
        print(f"teacher #{uid} created")
    elif cmd == "reopen-cross-review":
        n = db.reopen_for_cross_review()
        print(f"{n} words reopened for a second review (quorum is now {db.VERIFY_VOTES})")
    elif cmd == "run":
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "9100")), debug=os.environ.get("DEBUG") == "1")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    cli()
