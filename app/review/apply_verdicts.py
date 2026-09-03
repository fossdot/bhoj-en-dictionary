#!/usr/bin/env python3
"""Write review decisions back into data/canonical/.

  verified  → add_tag "verified" on every canonical entry for the word
  deleted   → delete_entry in every canonical file that has the word
  accepted edit → precise edit_gloss / edit_pos / add_example / add_sense /
                  delete_sense / edit_word actions (see content.findings)

The actions are written as a findings file in data/cleaning/ (the same
format the 2026-08 cleaning sweep used) and applied with
pipeline/apply_findings.py, so every change is logged the same way.

Usage:
    python3 app/review/apply_verdicts.py [--dry-run]

Afterwards: python3 pipeline/validate_canonical.py && make data dict review-import
(`make review-apply` does all of that.)
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db            # noqa: E402
import content       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CLEANING = ROOT / "data" / "cleaning"


def main() -> None:
    dry = "--dry-run" in sys.argv
    db.migrate()
    items = db.items_to_export()
    if not items:
        print("nothing to export", file=sys.stderr)
        return

    rows: list[dict] = []
    plan: list[tuple[dict, str, dict]] = []
    new_entries: list[dict] = []
    for it in items:
        cur = it["content"]
        if it["original"].get("new"):
            # a word suggested on the dictionary site: not in canonical yet
            if it["status"] == "verified":
                new_entries.append({
                    "word": cur["word"], "lang": "bho", "script": "Deva",
                    "translit": cur.get("translit", []), "phones": [],
                    "tags": [t for t in cur.get("tags", []) if t != "src:public"] + ["src:public", "verified"],
                    "senses": [{"pos": s.get("pos", ""), "gloss": s["gloss"], "examples": s.get("examples", [])}
                               for s in cur["senses"]],
                    "source": "public submission on the dictionary site, verified by reviewers",
                    "source_url": "", "license": "CC BY-SA 4.0"})
                plan.append((it, "verified", {k: v for k, v in cur.items() if k != "new"}))
            elif it["status"] == "deleted":
                plan.append((it, "deleted", cur))
            continue
        if it["status"] == "deleted":
            for f in it["original"]["sources"]:
                rows.append({"id": f"{f}:{it['original']['word']}", "action": "delete_entry",
                             "reason": f"review: {it['n_incorrect']} independent 'incorrect' verdicts"})
            plan.append((it, "deleted", cur))
            continue
        base = json.loads(it["exported_content"]) if it["exported_content"] else it["original"]
        rows += content.findings(base, cur)
        if it["status"] == "verified" and "verified" not in cur.get("tags", []):
            cur = {**cur, "tags": cur.get("tags", []) + ["verified"]}
            why = (f"review: {it['n_correct']} independent 'correct' verdicts" if it["n_incorrect"] == 0
                   else f"review: split vote ({it['n_correct']} correct / {it['n_incorrect']} incorrect) kept by a teacher")
            for f in it["original"]["sources"]:
                rows.append({"id": f"{f}:{it['original']['word']}", "action": "add_tag", "new_tag": "verified",
                             "reason": why})
        plan.append((it, it["status"], cur))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    CLEANING.mkdir(parents=True, exist_ok=True)
    findings_path = CLEANING / f"review-findings-{stamp}.jsonl"
    log_path = CLEANING / f"review-applied-{stamp}.jsonl"
    with findings_path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(items)} items → {len(rows)} actions → {findings_path}" + (f" + {len(new_entries)} new words" if new_entries else ""), file=sys.stderr)
    if dry:
        return

    if rows:
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "apply_findings.py"),
                        "--findings", str(findings_path), "--log", str(log_path)], check=True)
    if new_entries:
        community = ROOT / "data" / "canonical" / "community-bho.jsonl"
        have = {json.loads(l)["word"] for l in community.open() if l.strip()} if community.exists() else set()
        with community.open("a") as fh:
            for e in new_entries:
                if e["word"] not in have:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"{len(new_entries)} new public words → {community}", file=sys.stderr)
    for it, status, cur in plan:
        db.mark_exported(it["id"], status, cur)
    print(f"marked {len(plan)} items exported; log → {log_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
