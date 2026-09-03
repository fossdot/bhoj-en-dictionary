#!/usr/bin/env bash
# Nightly backup of both SQLite databases (online, consistent copies), 30-day rotation.
# crontab -e →  15 2 * * *  /srv/bhoj/deploy/backup.sh >> /srv/bhoj/deploy/backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
day=$(date +%F); out="backups/$day"; mkdir -p "$out"
python3 - "$out" <<'PY'
import sqlite3, sys, pathlib
out = pathlib.Path(sys.argv[1])
for src in ("../dictpress/data.db", "data/review/review.db"):
    p = pathlib.Path(src)
    if p.exists():
        dst = out / p.name
        s = sqlite3.connect(p); d = sqlite3.connect(dst); s.backup(d); d.close(); s.close()
        print("backed up", p, "→", dst, dst.stat().st_size // 1024, "KB")
PY
gzip -f "$out"/*.db
# pull public comments/suggestions from the dictionary into the review queue
REVIEW_DB="$PWD/data/review/review.db" python3 ../app/review/import_public.py --dict-db ../dictpress/data.db
find backups -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
echo "$(date -Is) ok"
