#!/usr/bin/env bash
# Publish review decisions to the live dictionary. Runs ON THE SERVER:
#
#     ssh root@<server> /srv/bhoj/deploy/publish.sh          # or add --dry-run
#
# 1. pulls the latest code/data from GitHub
# 2. pulls public comments/suggestions from the dictionary into the review queue
# 3. writes verified / deleted / edited decisions into data/canonical/ (logged in data/cleaning/)
# 4. validates, regenerates dictpress/import.csv
# 5. commits and pushes to GitHub (the server has a deploy key)
# 6. rebuilds the dictionary database and refreshes the review app (setup.sh)
#
# Running here, against the live review database, means no student verdict is
# ever lost to a copy race, and the repo stays the single source of truth.
set -euo pipefail
cd "$(dirname "$0")"
SELF="$PWD/$(basename "$0")"   # absolute: we have already changed directory

# Pull first, then re-run the freshly pulled copy of this script: bash reads a
# script incrementally, so updating the file underneath a running script breaks it.
if [ -z "${PUBLISH_REEXEC:-}" ]; then
  echo "→ git pull"; git -C .. pull -q --ff-only
  PUBLISH_REEXEC=1 exec bash "$SELF" "$@"
fi

exec </dev/null
DRY=""; [ "${1:-}" = "--dry-run" ] && DRY="--dry-run"
# everything below is also appended to deploy/publish.log
exec > >(tee -a publish.log) 2>&1
echo "===== publish $(date -u +%FT%TZ) ${DRY}"
export REVIEW_DB="$PWD/data/review/review.db"
CANONICAL=(wiktionary-bho wiktionary-translations-bho gatitos-bho hindi-cognates-bho aligned-bho langlinks-bho community-bho)

echo "→ public input → review queue"; python3 ../app/review/import_public.py --dict-db ../dictpress/data.db
echo "→ review decisions → data/canonical ${DRY}"; python3 ../app/review/apply_verdicts.py $DRY
if [ -n "$DRY" ]; then echo "(dry run: nothing written to canonical, nothing committed)"; exit 0; fi

echo "→ validate"; python3 ../pipeline/validate_canonical.py | tail -1
FILES=(); for f in "${CANONICAL[@]}"; do FILES+=("../data/canonical/$f.jsonl"); done
echo "→ dictpress/import.csv"; python3 ../pipeline/to_dictpress.py "${FILES[@]}" > ../dictpress/import.csv.new
# Replace it only when the content moved: the mtime is what tells us below
# whether the built dictionary is stale.
if cmp -s ../dictpress/import.csv.new ../dictpress/import.csv; then
  rm -f ../dictpress/import.csv.new
else
  mv ../dictpress/import.csv.new ../dictpress/import.csv
fi

cd ..
if git diff --quiet -- data/canonical data/cleaning dictpress/import.csv && [ -z "$(git ls-files --others --exclude-standard data/cleaning)" ]; then
  # Nothing of our own to commit — but the live databases are built from files,
  # not from git, so data pulled from a laptop still needs the rebuild. Ask the
  # artefacts rather than this run's history: an import.csv newer than the
  # database it was built into means the dictionary is stale, whoever changed
  # it. (Deciding from the pull cannot work: the copy of this script that runs
  # the pull is the old one, so it cannot pass on what the new one expects.)
  if [ ! -f dictpress/data.db ] || [ dictpress/import.csv -nt dictpress/data.db ]; then
    echo "nothing to publish, but the built dictionary is older than import.csv"
    echo "→ rebuilding dictionary"; ./deploy/setup.sh
    exit 0
  fi
  echo "nothing to publish"; exit 0
fi
git add data/canonical data/cleaning dictpress/import.csv
git commit -q -m "Publish review decisions ($(date -u +%Y-%m-%d))" && git push -q
echo "→ pushed $(git log --oneline -1)"
echo "→ rebuilding dictionary"; ./deploy/setup.sh
