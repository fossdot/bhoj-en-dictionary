#!/usr/bin/env python3
"""Apply verified quality-sweep findings to the canonical files.

Input:  data/cleaning/confirmed-findings.jsonl
        rows: {"id": "<file>:<word>", "action": "delete_entry" | "delete_sense"
               | "edit_gloss" | "add_tag", "sense_index": int?, "new_gloss": str?,
               "new_tag": str?, "reason": str}
Output: canonical files edited in place; every change (and every skipped
        finding) logged to data/cleaning/applied-log.jsonl.

Usage:
    python3 pipeline/apply_findings.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
FINDINGS = ROOT / "data" / "cleaning" / "confirmed-findings.jsonl"
LOG = ROOT / "data" / "cleaning" / "applied-log.jsonl"


def main() -> None:
    by_file: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    n_findings = 0
    for line in FINDINGS.open():
        f = json.loads(line)
        file, word = f["id"].split(":", 1)
        by_file[file][word].append(f)
        n_findings += 1

    log_rows = []
    stats = defaultdict(int)

    for file, by_word in by_file.items():
        path = CANON / f"{file}.jsonl"
        if not path.exists():
            for word, fs in by_word.items():
                for f in fs:
                    log_rows.append({**f, "applied": False, "why": "file not found"})
                    stats["skipped"] += 1
            continue

        entries = [json.loads(l) for l in path.open()]
        out = []
        for e in entries:
            fs = by_word.pop(e["word"], None)
            if not fs:
                out.append(e)
                continue

            drop_entry = False
            # dedupe identical (action, sense_index) findings
            seen_keys = set()
            # apply sense-level ops in descending index order so indexes stay valid
            fs_sorted = sorted(fs, key=lambda f: -(f.get("sense_index") or 0))
            for f in fs_sorted:
                key = (f["action"], f.get("sense_index"), f.get("new_gloss"), f.get("new_tag"))
                if key in seen_keys:
                    log_rows.append({**f, "applied": False, "why": "duplicate finding"})
                    stats["skipped"] += 1
                    continue
                seen_keys.add(key)
                act = f["action"]
                idx = f.get("sense_index")
                if act == "delete_entry":
                    drop_entry = True
                    log_rows.append({**f, "applied": True})
                    stats["delete_entry"] += 1
                elif act == "delete_sense":
                    if idx is not None and 0 <= idx < len(e["senses"]):
                        removed = e["senses"].pop(idx)
                        log_rows.append({**f, "applied": True, "old_gloss": removed["gloss"]})
                        stats["delete_sense"] += 1
                    else:
                        log_rows.append({**f, "applied": False, "why": f"sense_index {idx} out of range ({len(e['senses'])})"})
                        stats["skipped"] += 1
                elif act == "edit_gloss":
                    if idx is not None and 0 <= idx < len(e["senses"]) and f.get("new_gloss"):
                        old = e["senses"][idx]["gloss"]
                        e["senses"][idx]["gloss"] = f["new_gloss"].strip()
                        log_rows.append({**f, "applied": True, "old_gloss": old})
                        stats["edit_gloss"] += 1
                    else:
                        log_rows.append({**f, "applied": False, "why": "bad index or missing new_gloss"})
                        stats["skipped"] += 1
                elif act == "add_tag":
                    tag = (f.get("new_tag") or "").strip()
                    if tag and tag not in e.get("tags", []):
                        e.setdefault("tags", []).append(tag)
                        log_rows.append({**f, "applied": True})
                        stats["add_tag"] += 1
                    else:
                        log_rows.append({**f, "applied": False, "why": "empty or duplicate tag"})
                        stats["skipped"] += 1
                else:
                    log_rows.append({**f, "applied": False, "why": f"unknown action {act}"})
                    stats["skipped"] += 1

            if drop_entry:
                continue
            if not e["senses"]:
                log_rows.append({"id": f"{file}:{e['word']}", "action": "delete_entry",
                                 "applied": True, "why": "no senses left after deletions"})
                stats["delete_entry_empty"] += 1
                continue
            out.append(e)

        # findings whose word wasn't found in the file
        for word, fs in by_word.items():
            for f in fs:
                log_rows.append({**f, "applied": False, "why": "word not found in file"})
                stats["skipped"] += 1

        with path.open("w") as fh:
            for e in out:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"  {file}: {len(entries)} → {len(out)} entries", file=sys.stderr)

    with LOG.open("w") as fh:
        for row in log_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{n_findings} findings → {dict(stats)} → {LOG}", file=sys.stderr)


if __name__ == "__main__":
    main()
