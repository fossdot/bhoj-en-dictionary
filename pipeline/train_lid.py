#!/usr/bin/env python3
"""Train a Bhojpuri-vs-neighbors language identifier on VarDial 2018 ILI.

5 classes: BHO (Bhojpuri), HIN (Hindi), AWA (Awadhi), BRA (Braj), MAG (Magahi)
— exactly the confusion set that pollutes web corpora labeled "bho".

Model: char 1–4-gram TF-IDF + logistic regression (the standard strong
baseline for this shared task). Runs under the project venv:

    .venv/bin/python pipeline/train_lid.py            # train + report accuracy
    .venv/bin/python pipeline/train_lid.py --audit    # also classify the mono corpus

Artifacts: data/lid/model.joblib, data/lid/REPORT.md
"""

import sys
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "raw" / "vardial2018" / "dataset"
OUT = ROOT / "data" / "lid"
MONO = ROOT / "data" / "corpus" / "mono"


def load(name: str):
    X, y = [], []
    for ln in (DATA / name).read_text(errors="replace").splitlines():
        parts = ln.split("\t")
        if len(parts) == 2:
            X.append(parts[0])
            y.append(parts[1].strip())
    return X, y


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    Xtr, ytr = load("train.txt")
    Xdev, ydev = load("dev.txt")
    Xte, yte = load("gold.txt")

    model = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 4),
                                  min_df=2, sublinear_tf=True)),
        ("clf", LogisticRegression(max_iter=2000, C=4.0)),
    ])
    model.fit(Xtr + Xdev, ytr + ydev)

    pred = model.predict(Xte)
    acc = accuracy_score(yte, pred)
    report = classification_report(yte, pred, digits=3)
    print(f"test accuracy: {acc:.4f}", file=sys.stderr)
    print(report, file=sys.stderr)

    joblib.dump(model, OUT / "model.joblib")

    lines = [
        "# LID model report",
        "",
        "char 1-4gram TF-IDF + logistic regression, trained on VarDial 2018 ILI",
        f"(train+dev = {len(Xtr) + len(Xdev)} sentences), evaluated on the shared-task gold set.",
        "",
        f"**Test accuracy: {acc:.4f}** ({len(Xte)} sentences)",
        "",
        "```",
        report,
        "```",
    ]

    if "--audit" in sys.argv:
        lines += ["", "## Corpus audit (fraction of lines classified per language)", "",
                  "| file | lines | BHO | HIN | AWA | BRA | MAG |", "|---|---:|---:|---:|---:|---:|---:|"]
        for f in sorted(MONO.glob("*.txt")):
            if f.name == "bhwiki-titles.txt":
                continue
            sents = [ln for ln in f.read_text().splitlines() if len(ln) > 20][:50000]
            if not sents:
                continue
            preds = model.predict(sents)
            n = len(preds)
            frac = {lang: 100 * sum(p == lang for p in preds) / n for lang in ("BHO", "HIN", "AWA", "BRA", "MAG")}
            lines.append(f"| {f.name} | {n} | " + " | ".join(f"{frac[l]:.0f}%" for l in ("BHO", "HIN", "AWA", "BRA", "MAG")) + " |")
            print(f"  {f.name}: BHO {frac['BHO']:.0f}% HIN {frac['HIN']:.0f}% AWA {frac['AWA']:.0f}%", file=sys.stderr)

    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT}/REPORT.md and model.joblib", file=sys.stderr)


if __name__ == "__main__":
    main()
