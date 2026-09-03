# bhoj — build the dictionary + LLM data from sources
#
#   make fetch       download/refresh raw sources that have fetchers
#   make data        canonical JSONL → corpus, dictionary CSV, training exports
#   make dict        (re)install DB, import CSV, restart the dictpress container
#   make eval-test   self-test the chrF scorer
#   make all         fetch + data + dict
#
#   make review-import  load canonical → app/review/review.db (run after every `make data`)
#   make review-run     dev server for the student review app on :9100
#   make review-public  pull public comments/suggestions from dictpress/data.db into the review queue
#   make review-apply   write review decisions back to canonical, revalidate, regenerate import.csv (then `make dict` to see it)

PY := python3
DICT := dictpress
DOCKER_RUN := docker run --rm -v "$(PWD)/$(DICT):/work" -w /work/app alpine

# NOTE: `make dict` rebuilds data.db from these files — website submissions
# approved in the admin live only in data.db until exported into
# community-bho.jsonl, so export before rebuilding or they are lost.
CANONICAL := data/canonical/wiktionary-bho.jsonl \
             data/canonical/wiktionary-translations-bho.jsonl \
             data/canonical/gatitos-bho.jsonl \
             data/canonical/hindi-cognates-bho.jsonl \
             data/canonical/aligned-bho.jsonl \
             data/canonical/langlinks-bho.jsonl \
             data/canonical/community-bho.jsonl

all: fetch data dict

fetch:
	$(PY) pipeline/fetch_wiktionary.py
	$(PY) pipeline/fetch_wiktionary_translations.py
	$(PY) pipeline/fetch_gatitos.py
	$(PY) pipeline/fetch_langlinks.py
	$(PY) pipeline/fetch_hindi_cognates.py
	$(PY) pipeline/mine_alignments.py   # needs data/corpus/parallel (run 'make data' corpus step first on a fresh clone)

data:
	$(PY) pipeline/extract_bhwiki.py
	$(PY) pipeline/build_corpus.py
	$(PY) pipeline/to_dictpress.py $(CANONICAL) > $(DICT)/import.csv
	$(PY) pipeline/to_training.py data/canonical/*.jsonl
	$(PY) pipeline/assemble_sft.py
	$(PY) pipeline/assemble_sft.py --include-nc

dict:
	docker rm -f bhoj-dict 2>/dev/null || true
	rm -f $(DICT)/data.db
	$(DOCKER_RUN) sh -c "./dictpress --config ../config.toml --db ../data.db install --yes && \
	  ./dictpress --config ../config.toml --db ../data.db import --file ../import.csv"
	# dictpress ranks results as bm25 + entry weight, with a fixed -1000 boost for
	# exact headword matches. Import assigns weight by row order (0..N), so with
	# 20k entries the boost is swamped and a common phonetic neighbour outranks
	# the word the user typed. Compress weights into 0..999 so the exact-match
	# boost always wins, while frequency order still breaks ties inside a bucket.
	sqlite3 $(DICT)/data.db "UPDATE entries SET weight = ROUND(weight * 999.0 / (SELECT MAX(weight) FROM entries), 2);"
	docker run -d --name bhoj-dict --restart unless-stopped -p 9000:9000 \
	  -v "$(PWD)/$(DICT):/work" -w /work/app alpine \
	  ./dictpress --config ../config.toml --db ../data.db --site ../site
	@echo "dictionary → http://localhost:9000  admin → http://localhost:9000/admin"

# ---- student review app (app/review) --------------------------------------
REVIEW_PY := .venv/bin/python

review-import:
	$(REVIEW_PY) app/review/import_items.py $(CANONICAL)

review-run:
	$(REVIEW_PY) app/review/app.py run

review-public:
	$(REVIEW_PY) app/review/import_public.py --dict-db dictpress/data.db

# local equivalent of deploy/publish.sh (the server runs that one against the live review.db)
review-apply:
	$(REVIEW_PY) app/review/apply_verdicts.py
	$(PY) pipeline/validate_canonical.py
	$(PY) pipeline/to_dictpress.py $(CANONICAL) > $(DICT)/import.csv
	$(MAKE) review-import

eval-test:
	@$(PY) -c "import json; refs=[json.loads(l)['bho'] for l in open('data/corpus/parallel/flores200-dev-EVAL-ONLY.jsonl')][:50]; open('/tmp/bhoj-eval-refs.txt','w').write(chr(10).join(refs))"
	$(PY) eval/score.py --hyp /tmp/bhoj-eval-refs.txt --ref /tmp/bhoj-eval-refs.txt

.PHONY: all fetch data dict eval-test review-import review-run review-public review-apply
