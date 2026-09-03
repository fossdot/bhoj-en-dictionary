#!/usr/bin/env bash
# One-time server setup (re-runnable): fetch the dictpress binary for this CPU,
# write the production config, build the dictionary database from import.csv,
# build the review database from the canonical data, start the stack.
set -euo pipefail
cd "$(dirname "$0")"
exec </dev/null   # docker would otherwise hold an ssh session's stdin open and hang the caller
[ -f .env ] || { echo "deploy/.env missing — cp .env.example .env and edit it"; exit 1; }
set -a; source .env; set +a
for v in DICT_DOMAIN REVIEW_DOMAIN DICT_ADMIN_USER DICT_ADMIN_PASSWORD REVIEW_INVITE_CODE REVIEW_SECRET_KEY; do
  [[ "${!v:-}" == "" || "${!v}" == change-me* ]] && { echo "set $v in deploy/.env"; exit 1; }
done

VER=5.0.0-rc5
case "$(uname -m)" in
  x86_64)  ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) echo "unsupported CPU $(uname -m)"; exit 1 ;;
esac

echo "→ dictpress v$VER ($ARCH)"
mkdir -p ../dictpress/app
if [ ! -x ../dictpress/app/dictpress ] || ! ../dictpress/app/dictpress --version 2>/dev/null | grep -q "$VER"; then
  curl -fsSL "https://github.com/knadh/dictpress/releases/download/v$VER/dictpress_${VER}_${ARCH}-unknown-linux-musl.tar.gz" \
    | tar -xz -C ../dictpress/app
fi

echo "→ production config"
sed -e "s|^root_url = .*|root_url = \"https://${DICT_DOMAIN}\"|" \
    -e "s|^admin_username = .*|admin_username = \"${DICT_ADMIN_USER}\"|" \
    -e "s|^admin_password = .*|admin_password = \"${DICT_ADMIN_PASSWORD}\"|" \
    -e '/^\[cache\]/,/^\[/ s|^enabled = false|enabled = true|' \
    ../dictpress/config.toml > config.prod.toml
chmod 600 config.prod.toml

if [ -f ../dictpress/data.db ]; then
  echo "→ public comments/submissions from the live dictionary → review queue"
  mkdir -p data/review
  REVIEW_DB="$PWD/data/review/review.db" python3 ../app/review/import_public.py --dict-db ../dictpress/data.db
fi

echo "→ dictionary database from dictpress/import.csv (built beside the live one, then swapped)"
rm -f ../dictpress/data.db.new ../dictpress/data.db.new-*
docker run --rm -v "$PWD/../dictpress:/work" -v "$PWD/config.prod.toml:/work/config.prod.toml:ro" -w /work/app alpine:3.20 \
  sh -c "./dictpress --config ../config.prod.toml --db ../data.db.new install --yes && \
         ./dictpress --config ../config.prod.toml --db ../data.db.new import --file ../import.csv"
# same weight compression as `make dict`: keep exact-match boost above bm25+weight
python3 - <<'PY'
import sqlite3
con = sqlite3.connect("../dictpress/data.db.new")
con.execute("UPDATE entries SET weight = ROUND(weight * 999.0 / (SELECT MAX(weight) FROM entries), 2)")
con.commit(); con.execute("VACUUM"); print("  entries:", con.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
PY
rm -f ../dictpress/data.db-wal ../dictpress/data.db-shm
mv -f ../dictpress/data.db.new ../dictpress/data.db

echo "→ review database from data/canonical"
mkdir -p data/review
REVIEW_DB="$PWD/data/review/review.db" python3 ../app/review/import_items.py

echo "→ starting containers"
docker compose up -d --build
docker compose restart dict >/dev/null 2>&1 || true   # pick up the swapped database
echo
echo "dictionary: https://$DICT_DOMAIN     admin: https://$DICT_DOMAIN/admin"
echo "review:     https://$REVIEW_DOMAIN   (first account to register becomes the teacher, or run:"
echo "            REVIEW_DB=$PWD/data/review/review.db python3 ../app/review/app.py create-teacher <user> \"<Name>\")"
