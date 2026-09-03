#!/usr/bin/env python3
"""Apply verified quality-sweep findings to the canonical files.

Input:  data/cleaning/confirmed-findings.jsonl (or --findings PATH)
        rows: {"id": "<file>:<word>", "action": <see below>, "reason": str, ...}
          delete_entry
          delete_sense  sense_index
          edit_gloss    sense_index, new_gloss
          edit_pos      sense_index, new_pos
          add_example   sense_index, bho, en?
          add_sense     pos?, gloss, examples?
          add_tag       new_tag
          edit_word     new_word          (skipped if new_word already exists in the file)
Output: canonical files edited in place; every change (and every skipped
        finding) logged to data/cleaning/applied-log.jsonl (or --log PATH).

Usage:
    python3 pipeline/apply_findings.py [--findings PATH] [--log PATH]

The review app (app/review/apply_verdicts.py) generates findings in this
format from student verdicts, so both flows share one audit trail.
"""

import argparse

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
FINDINGS = ROOT / "data" / "cleaning" / "confirmed-findings.jsonl"
LOG = ROOT / "data" / "cleaning" / "applied-log.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", type=Path, default=FINDINGS)
    ap.add_argument("--log", type=Path, default=LOG)
    args = ap.parse_args()
    findings_path, log_path = args.findings, args.log

    by_file: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    n_findings = 0
    for line in findings_path.open():
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
        words_in_file = {x["word"] for x in entries}
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
                elif act == "edit_pos":
                    if idx is not None and 0 <= idx < len(e["senses"]):
                        old = e["senses"][idx].get("pos", "")
                        e["senses"][idx]["pos"] = (f.get("new_pos") or "").strip()
                        log_rows.append({**f, "applied": True, "old_pos": old})
                        stats["edit_pos"] += 1
                    else:
                        log_rows.append({**f, "applied": False, "why": f"sense_index {idx} out of range"})
                        stats["skipped"] += 1
                elif act == "add_example":
                    bho = (f.get("bho") or "").strip()
                    if idx is not None and 0 <= idx < len(e["senses"]) and bho:
                        ex = {"bho": bho}
                        if (f.get("en") or "").strip():
                            ex["en"] = f["en"].strip()
                        exs = e["senses"][idx].setdefault("examples", [])
                        if any(x.get("bho") == bho for x in exs):
                            log_rows.append({**f, "applied": False, "why": "example already present"})
                            stats["skipped"] += 1
                        else:
                            exs.append(ex)
                            log_rows.append({**f, "applied": True})
                            stats["add_example"] += 1
                    else:
                        log_rows.append({**f, "applied": False, "why": "bad index or empty example"})
                        stats["skipped"] += 1
                elif act == "add_sense":
                    gloss = (f.get("gloss") or "").strip()
                    if gloss and gloss.lower() not in {s["gloss"].lower() for s in e["senses"]}:
                        sense = {"pos": (f.get("pos") or "").strip(), "gloss": gloss,
                                 "examples": [x for x in (f.get("examples") or []) if x.get("bho")]}
                        e["senses"].append(sense)
                        log_rows.append({**f, "applied": True})
                        stats["add_sense"] += 1
                    else:
                        log_rows.append({**f, "applied": False, "why": "empty or duplicate gloss"})
                        stats["skipped"] += 1
                elif act == "edit_word":
                    new_word = (f.get("new_word") or "").strip()
                    if new_word and new_word != e["word"] and new_word not in words_in_file:
                        log_rows.append({**f, "applied": True, "old_word": e["word"]})
                        words_in_file.discard(e["word"])
                        words_in_file.add(new_word)
                        e["word"] = new_word
                        stats["edit_word"] += 1
                    else:
                        log_rows.append({**f, "applied": False, "why": "empty, unchanged, or already exists in file"})
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

    with log_path.open("w") as fh:
        for row in log_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{n_findings} findings → {dict(stats)} → {log_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
