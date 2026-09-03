# Going live

One small Linux server runs everything: the dictionary (dictpress), the student
review app, and Caddy for HTTPS. Everything is state in two SQLite files.

## 1. Before the server

- Push the repository to GitHub (the server clones it).
- Get a VPS: Ubuntu 24.04, 1 vCPU, **1 GB RAM** (the $6 tier on DigitalOcean
  Bangalore, or equivalent). 512 MB works too if you add swap (below). Note its public IP.
- DNS: two **A records** pointing at that IP, e.g. `bhoj.hikmatfoundation.org`
  and `review.bhoj.hikmatfoundation.org`. Wait until `dig +short <domain>` shows the IP.

## 2. On the server

```sh
# as root, once
apt update && apt install -y git python3 curl
curl -fsSL https://get.docker.com | sh

# recommended on 1 GB, required on 512 MB: 1 GB swap so builds never hit the OOM killer
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

mkdir -p /srv && cd /srv
git clone https://github.com/fossdot/bhoj-en-dictionary.git bhoj
cd bhoj/deploy
cp .env.example .env
nano .env            # domains, admin password, invite code, secret key
openssl rand -hex 32 # paste as REVIEW_SECRET_KEY

./setup.sh
```

`setup.sh` downloads the right dictpress binary for the server's CPU, writes
`config.prod.toml` (production URL, admin password, cache on), builds
`dictpress/data.db` from the committed `import.csv`, builds the review database
from `data/canonical/`, and starts the three containers. Caddy fetches the TLS
certificates on first request; give it a minute.

Then create the teacher account:

```sh
REVIEW_DB=/srv/bhoj/deploy/data/review/review.db python3 ../app/review/app.py create-teacher vishal "Vishal Arya"
```

Students sign up at `https://review.<domain>/register` with the invite code.

## 3. Backups

```sh
crontab -e
# add:
15 2 * * *  /srv/bhoj/deploy/backup.sh >> /srv/bhoj/deploy/backups/backup.log 2>&1
```

Copies land in `deploy/backups/<date>/` as gzipped SQLite files, kept 30 days.
The same nightly job pulls public comments and word suggestions from the
dictionary into the review queue.
Copy that folder off the server periodically (rsync, or a provider snapshot).

## 4. Routine operations

| Task | Command (in `/srv/bhoj`) |
|---|---|
| Deploy a code or data change | `git pull && cd deploy && ./setup.sh` — pulls public comments/suggestions into the review queue, then rebuilds the dictionary database from the repo and refreshes the review database in place |
| **Publish review decisions** | `ssh root@<server> /srv/bhoj/deploy/publish.sh` — applies verified/deleted/edited decisions to `data/canonical/`, commits and pushes, rebuilds the live dictionary. Add `--dry-run` to see what would change. Then `git pull` on your laptop. |
| Update only the review app | `cd deploy && docker compose up -d --build review` |
| Logs | `docker compose logs -f review` / `dict` / `caddy` |
| Restart everything | `docker compose restart` |

Publishing runs on the server against the live review database so no verdict
is lost to a copy race; it still goes through git (the server pushes with a
deploy key), so every change is logged in `data/cleaning/` and reviewable.

## Files

- `docker-compose.yml` — the three services
- `Caddyfile` — HTTPS reverse proxy, domains from `.env`
- `.env.example` — copy to `.env` (never committed)
- `setup.sh` — build/refresh both databases and start
- `backup.sh` — nightly SQLite backups
- `publish.sh` — review decisions → canonical → GitHub → live dictionary (run on the server)
- `config.prod.toml`, `data/`, `backups/` — generated on the server, not committed
