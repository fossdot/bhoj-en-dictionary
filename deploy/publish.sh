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

# Pull first, then re-run the freshly pulled copy of this script: bash reads a
# script incrementally, so updating the file underneath a running script breaks it.
if [ -z "${PUBLISH_REEXEC:-}" ]; then
  echo "→ git pull"
  before=$(git -C .. rev-parse HEAD)
  git -C .. pull -q --ff-only
  [ "$before" = "$(git -C .. rev-parse HEAD)" ] && pulled=0 || pulled=1
  PUBLISH_REEXEC=1 PUBLISH_PULLED=$pulled exec bash "$0" "$@"
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
mv ../dictpress/import.csv.new ../dictpress/import.csv

cd ..
if git diff --quiet -- data/canonical data/cleaning dictpress/import.csv && [ -z "$(git ls-files --others --exclude-standard data/cleaning)" ]; then
  # No decisions of our own to commit. The pull may still have brought new
  # canonical data from a laptop, and the live databases are built from files,
  # not from git — so they need the rebuild even when there is nothing to push.
  if [ "${PUBLISH_PULLED:-0}" = "1" ]; then
    echo "nothing to publish, but the pull brought new data"
    echo "→ rebuilding dictionary"; ./deploy/setup.sh
    exit 0
  fi
  echo "nothing to publish"; exit 0
fi
git add data/canonical data/cleaning dictpress/import.csv
git commit -q -m "Publish review decisions ($(date -u +%Y-%m-%d))" && git push -q
echo "→ pushed $(git log --oneline -1)"
echo "→ rebuilding dictionary"; ./deploy/setup.sh
