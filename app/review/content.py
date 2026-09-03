"""Item content helpers shared by the web app and the export script.

Item content shape (one merged headword, as the dictionary site shows it):

    {"word": "मड़ई", "translit": ["maṛaī"], "tags": ["src:..."],
     "sources": ["wiktionary-bho", "langlinks-bho"],          # canonical files
     "senses": [{"pos": "noun", "gloss": "thatched hut",
                 "examples": [{"bho": "...", "en": "..."}],
                 "origins": [{"file": "wiktionary-bho", "idx": 0}]}]}

`origins` maps a merged sense back to (file, sense index) in canonical so an
accepted edit can be turned into precise apply_findings actions. A sense a
student added has no origins.
"""

from __future__ import annotations


def merge(word: str, entries: list[tuple[str, dict]]) -> dict:
    """Merge the same headword from several canonical files (file order = priority),
    the same way pipeline/to_dictpress.py does, but remembering where each sense came from."""
    translit: list[str] = []
    tags: list[str] = []
    senses: list[dict] = []
    by_gloss: dict[str, dict] = {}
    for file, e in entries:
        translit += [t for t in e.get("translit", []) if t not in translit]
        tags += [t for t in e.get("tags", []) if t not in tags]
        for idx, s in enumerate(e.get("senses", [])):
            key = s["gloss"].strip().lower()
            origin = {"file": file, "idx": idx}
            if key in by_gloss:
                by_gloss[key]["origins"].append(origin)
                for ex in s.get("examples", []) or []:
                    if ex not in by_gloss[key]["examples"]:
                        by_gloss[key]["examples"].append(ex)
                continue
            sense = {"pos": s.get("pos", ""), "gloss": s["gloss"].strip(),
                     "examples": list(s.get("examples", []) or []), "origins": [origin]}
            by_gloss[key] = sense
            senses.append(sense)
    return {"word": word, "translit": translit, "tags": tags,
            "sources": [f for f, _ in entries], "senses": senses}


def _ex_key(ex: dict) -> tuple[str, str]:
    return (ex.get("bho", "").strip(), ex.get("en", "").strip())


def diff(old: dict, new: dict) -> list[dict]:
    """Human-readable list of changes between two contents: [{what, old, new}]."""
    changes: list[dict] = []
    if old["word"] != new["word"]:
        changes.append({"what": "word", "old": old["word"], "new": new["word"]})
    old_by_origin = {}
    for s in old["senses"]:
        for o in s.get("origins", []):
            old_by_origin[(o["file"], o["idx"])] = s
    matched = set()
    for s in new["senses"]:
        origins = [(o["file"], o["idx"]) for o in s.get("origins", [])]
        base = next((old_by_origin[k] for k in origins if k in old_by_origin), None)
        if base is None:
            changes.append({"what": "new sense", "old": "",
                            "new": f"{s.get('pos', '')} — {s['gloss']}".strip(" —")})
            for ex in s.get("examples", []):
                changes.append({"what": "new example", "old": "", "new": _fmt_ex(ex)})
            continue
        matched.add(id(base))
        if base["gloss"].strip() != s["gloss"].strip():
            changes.append({"what": "meaning", "old": base["gloss"], "new": s["gloss"]})
        if (base.get("pos") or "") != (s.get("pos") or ""):
            changes.append({"what": "part of speech", "old": base.get("pos", ""), "new": s.get("pos", "")})
        old_ex = {_ex_key(e) for e in base.get("examples", [])}
        new_ex = {_ex_key(e) for e in s.get("examples", [])}
        for ex in s.get("examples", []):
            if _ex_key(ex) not in old_ex:
                changes.append({"what": "new example", "old": "", "new": _fmt_ex(ex)})
        for ex in base.get("examples", []):
            if _ex_key(ex) not in new_ex:
                changes.append({"what": "removed example", "old": _fmt_ex(ex), "new": ""})
    for s in old["senses"]:
        if id(s) not in matched:
            changes.append({"what": "removed sense", "old": f"{s.get('pos', '')} — {s['gloss']}".strip(" —"), "new": ""})
    return changes


def _fmt_ex(ex: dict) -> str:
    return f"{ex.get('bho', '')} — {ex.get('en', '')}".strip(" —")


def findings(old: dict, new: dict) -> list[dict]:
    """Turn an accepted edit into pipeline/apply_findings.py actions.

    Sense-level actions carry the original sense index in the original file;
    apply_findings applies them in descending index order so they stay valid.
    Examples that a student *removed* are deliberately not exported: removing
    parallel text needs a maintainer's eye, and the diff view shows it.
    """
    word = old["word"]
    files = old["sources"] or [new["sources"][0]]
    acts: list[dict] = []

    def act(file: str, **kw) -> None:
        acts.append({"id": f"{file}:{word}", **kw})

    old_by_origin = {}
    for s in old["senses"]:
        for o in s.get("origins", []):
            old_by_origin[(o["file"], o["idx"])] = s
    seen_origins: set[tuple[str, int]] = set()
    for s in new["senses"]:
        origins = [(o["file"], o["idx"]) for o in s.get("origins", []) if (o["file"], o["idx"]) in old_by_origin]
        if not origins:
            act(files[0], action="add_sense", pos=s.get("pos", ""), gloss=s["gloss"].strip(),
                examples=[e for e in s.get("examples", []) if e.get("bho", "").strip()],
                reason="review: sense added")
            continue
        base = old_by_origin[origins[0]]
        base_ex = {_ex_key(e) for e in base.get("examples", [])}
        for file, idx in origins:
            seen_origins.add((file, idx))
            if base["gloss"].strip() != s["gloss"].strip():
                act(file, action="edit_gloss", sense_index=idx, new_gloss=s["gloss"].strip(),
                    reason="review: meaning corrected")
            if (base.get("pos") or "") != (s.get("pos") or ""):
                act(file, action="edit_pos", sense_index=idx, new_pos=s.get("pos", ""),
                    reason="review: part of speech corrected")
        # examples go to the first origin only, so they aren't duplicated across files
        file, idx = origins[0]
        for ex in s.get("examples", []):
            if ex.get("bho", "").strip() and _ex_key(ex) not in base_ex:
                act(file, action="add_example", sense_index=idx, bho=ex["bho"].strip(),
                    en=ex.get("en", "").strip(), reason="review: example added")
    for (file, idx) in old_by_origin:
        if (file, idx) not in seen_origins:
            act(file, action="delete_sense", sense_index=idx, reason="review: sense removed")
    if new["word"].strip() != word:
        for file in files:
            act(file, action="edit_word", new_word=new["word"].strip(), reason="review: spelling corrected")
    return acts


def from_form(form, base: dict) -> dict:
    """Build a proposed content from the edit form. `base` supplies origins.

    Field names (see templates/edit.html):
      word
      s{k}-pos, s{k}-gloss, s{k}-delete          for k in range(len(base.senses))
      s{k}-ex{j}-bho, s{k}-ex{j}-en              existing examples (blank bho = remove)
      s{k}-newex-bho, s{k}-newex-en              one new example per sense
      n{k}-pos, n{k}-gloss, n{k}-ex-bho, n{k}-ex-en   new senses, k = 0..
    """
    new = {"word": (form.get("word") or base["word"]).strip(), "translit": base.get("translit", []),
           "tags": base.get("tags", []), "sources": base.get("sources", []), "senses": []}
    if base.get("new"):
        new["new"] = True
    for k, s in enumerate(base["senses"]):
        if form.get(f"s{k}-delete"):
            continue
        gloss = (form.get(f"s{k}-gloss") or "").strip()
        if not gloss:
            continue
        examples = []
        for j, _ in enumerate(s.get("examples", [])):
            bho = (form.get(f"s{k}-ex{j}-bho") or "").strip()
            if bho:
                examples.append({"bho": bho, "en": (form.get(f"s{k}-ex{j}-en") or "").strip()})
        bho = (form.get(f"s{k}-newex-bho") or "").strip()
        if bho:
            examples.append({"bho": bho, "en": (form.get(f"s{k}-newex-en") or "").strip()})
        new["senses"].append({"pos": (form.get(f"s{k}-pos") or "").strip(), "gloss": gloss,
                              "examples": examples, "origins": s.get("origins", [])})
    k = 0
    while f"n{k}-gloss" in form:
        gloss = (form.get(f"n{k}-gloss") or "").strip()
        if gloss:
            examples = []
            bho = (form.get(f"n{k}-ex-bho") or "").strip()
            if bho:
                examples.append({"bho": bho, "en": (form.get(f"n{k}-ex-en") or "").strip()})
            new["senses"].append({"pos": (form.get(f"n{k}-pos") or "").strip(), "gloss": gloss,
                                  "examples": examples, "origins": []})
        k += 1
    return new
