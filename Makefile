# bhoj — build the dictionary + LLM data from sources
#
#   make fetch       download/refresh raw sources that have fetchers
#   make data        canonical JSONL → corpus, dictionary CSV, training exports
#   make dict        (re)install DB, import CSV, restart the dictpress container
#   make eval-test   self-test the chrF scorer
#   make all         fetch + data + dict

PY := python3
DICT := dictpress
DOCKER_RUN := docker run --rm -v "$(PWD)/$(DICT):/work" -w /work/app alpine

CANONICAL := data/canonical/wiktionary-bho.jsonl \
             data/canonical/wiktionary-translations-bho.jsonl \
             data/canonical/gatitos-bho.jsonl \
             data/canonical/hindi-cognates-bho.jsonl \
             data/canonical/aligned-bho.jsonl \
             data/canonical/langlinks-bho.jsonl

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
	docker run -d --name bhoj-dict --restart unless-stopped -p 9000:9000 \
	  -v "$(PWD)/$(DICT):/work" -w /work/app alpine \
	  ./dictpress --config ../config.toml --db ../data.db --site ../site
	@echo "dictionary → http://localhost:9000  admin → http://localhost:9000/admin"

eval-test:
	@$(PY) -c "import json; refs=[json.loads(l)['bho'] for l in open('data/corpus/parallel/flores200-dev-EVAL-ONLY.jsonl')][:50]; open('/tmp/bhoj-eval-refs.txt','w').write(chr(10).join(refs))"
	$(PY) eval/score.py --hyp /tmp/bhoj-eval-refs.txt --ref /tmp/bhoj-eval-refs.txt

.PHONY: all fetch data dict eval-test
