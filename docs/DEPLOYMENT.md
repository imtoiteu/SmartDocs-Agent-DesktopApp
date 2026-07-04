# SmartDocs-Agent — Production Deployment

For installation and local development see [INSTALLATION.md](./INSTALLATION.md). This guide
covers running SmartDocs-Agent as a long-lived service on a Linux server, behind a reverse
proxy, with sane security and backups.

Everything is verified against the repository. Where the repo does not ship a particular
production artifact (it ships only the Flask dev-server entrypoint), the recommended pattern
is labelled as such, and unverifiable specifics are marked **UNKNOWN**.

---

## 1. Important architecture facts that shape deployment

These come directly from the code and determine how you must deploy:

1. **The entrypoint is the Flask dev server.** `app.py`'s `__main__` block calls
   `app.run(..., threaded=True)`. The repo ships **no** WSGI server (`gunicorn`/`waitress`
   are not in `requirements.txt`). You add one for production.

2. **Bootstrap runs only under `python app.py`.** `seed_admin(app)` (DB create + seed),
   `ai_rewrite_service.prewarm()`, and `chat_service.rebuild_indexes_from_db(app)` are all
   inside `__main__`. A WSGI server importing `app:app` will **not** run them automatically —
   you must trigger DB init and (optionally) index rebuild yourself (see §3).

3. **State is in-process and in-memory.** The RAG index lives in a per-process dict
   (`services/chat_service.py`); the Qwen/PhoBERT/embedding models load into process memory.
   Therefore run **a single worker** (`gunicorn -w 1`). Multiple workers would each load a
   full copy of the models (memory blow-up) and maintain *separate, inconsistent* RAG indexes.
   Use **threads** for concurrency, not workers.

4. **SQLite, no migrations.** Schema is created by `db.create_all()`; there is no Alembic.
   The DB file is `paddleocr.db` (or `DB_PATH`).

5. **No CSRF protection** exists in the app (verified). Cookies are `SameSite=Lax` only.
   This affects how you expose the admin UI (see §6).

---

## 2. Linux server deployment

```bash
# 1. System packages + project
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv python3-pip git \
    libgl1 libglib2.0-0
sudo useradd --system --create-home --shell /usr/sbin/nologin smartdocs   # service user

# 2. Place the project (e.g. /opt/smartdocs-agent) owned by the service user
sudo chown -R smartdocs:smartdocs /opt/smartdocs-agent
cd /opt/smartdocs-agent

# 3. venv + deps + production WSGI server (gunicorn is NOT in requirements)
sudo -u smartdocs python3.10 -m venv .venv
sudo -u smartdocs .venv/bin/pip install --upgrade pip
sudo -u smartdocs .venv/bin/pip install -r requirements.txt
sudo -u smartdocs .venv/bin/pip install gunicorn

# 4. Configure environment
sudo -u smartdocs cp .env.example .env
sudo -u smartdocs nano .env       # set SECRET_KEY, HOST=127.0.0.1, provider keys, etc.
sudo chmod 600 .env               # .env contains API keys
```

Recommended `.env` overrides for production:

```ini
HOST=127.0.0.1                 # only the reverse proxy reaches the app
PORT=5001
SECRET_KEY=<long-random-string># REQUIRED for stable sessions (else random per process)
SESSION_COOKIE_SECURE=1        # you are terminating TLS at the proxy
MAX_UPLOAD_MB=50               # keep in sync with nginx client_max_body_size
# OFFLINE=1                    # if the box has no outbound internet (cloud LLMs then unavailable)
```

> Apple-Silicon-only **GLM-OCR** (MLX) is not available on a typical Linux server — the other
> three OCR engines work. See [INSTALLATION.md §6](./INSTALLATION.md).

---

## 3. Initialize the database (one-time, required for WSGI)

Because `seed_admin` does not run under gunicorn, create + seed the DB once:

```bash
sudo -u smartdocs .venv/bin/python -c "from app import app; from models import seed_admin; seed_admin(app)"
```

This runs `db.create_all()` and seeds `admin/admin123` + `user/user123`.
**Log in and change both passwords immediately** (`/admin`).

### Recommended: a `wsgi.py` entrypoint (create this file)

To also reproduce the dev server's startup work (DB init + RAG index rebuild from persisted
artifacts) under gunicorn, create `wsgi.py` in the project root:

```python
# wsgi.py — production WSGI entrypoint (you create this; not shipped in the repo)
from app import app
from models import seed_admin
import services.chat_service as chat_service

seed_admin(app)                              # db.create_all() + seed users (idempotent)
chat_service.rebuild_indexes_from_db(app)    # rebuild in-memory RAG index from DB artifacts
# ai_rewrite_service.prewarm() already runs on import; chat model loads on first request.
```

Without the `rebuild_indexes_from_db` call, the RAG index starts empty after a restart and
is repopulated lazily as documents are (re)processed — chat over previously-indexed docs
would otherwise miss them until re-indexed.

---

## 4. Process management (systemd + gunicorn)

Create `/etc/systemd/system/smartdocs.service`:

```ini
[Unit]
Description=SmartDocs-Agent
After=network.target

[Service]
Type=simple
User=smartdocs
Group=smartdocs
WorkingDirectory=/opt/smartdocs-agent
# config.py loads .env via python-dotenv from WorkingDirectory — no EnvironmentFile needed.
ExecStart=/opt/smartdocs-agent/.venv/bin/gunicorn \
    --workers 1 --threads 4 \
    --timeout 600 \
    --bind 127.0.0.1:5001 \
    wsgi:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now smartdocs
sudo systemctl status smartdocs
journalctl -u smartdocs -f          # logs
```

Notes:
- `--workers 1` is deliberate (§1.3). Scale concurrency with `--threads`, not workers.
- `--timeout 600`: OCR of a large PDF or local LLM generation can take minutes
  (`GLM_TIMEOUT` alone is 300s). The default 30s would kill long requests.
- If you skipped `wsgi.py`, use `app:app` instead of `wsgi:app` **after** running the
  one-time DB init in §3.
- **Windows production**: gunicorn is Unix-only — use `waitress`
  (`pip install waitress`; `waitress-serve --listen=127.0.0.1:5001 wsgi:app`). The single-
  process model constraint still applies.

---

## 5. Reverse proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name smartdocs.example.com;

    ssl_certificate     /etc/letsencrypt/live/smartdocs.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/smartdocs.example.com/privkey.pem;

    # Must be >= MAX_UPLOAD_MB (default 50 MB) or uploads get a 413 at the proxy.
    client_max_body_size 60m;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # OCR / LLM requests are slow — raise read/send timeouts well past the default.
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
# Redirect HTTP → HTTPS on :80 as usual.
```

Notes:
- Terminate TLS at nginx and set `SESSION_COOKIE_SECURE=1` in `.env`.
- `client_max_body_size` must be ≥ `MAX_UPLOAD_MB`.
- The app does **not** apply Werkzeug `ProxyFix` (verified), so `activity_logs.ip_address`
  records the proxy IP (`127.0.0.1`) rather than the client IP. If you need real client IPs
  in the audit log, add `ProxyFix` to the app (optional enhancement; not in the repo).

---

## 6. Security considerations

| Area | Action |
|---|---|
| **Default credentials** | Change `admin/admin123` and `user/user123` immediately after first login. They are seeded by `models.py` and printed at startup. |
| **SECRET_KEY** | Set a fixed long random value. If unset, the key is random per process → all sessions invalidate on restart. |
| **HTTPS** | Terminate TLS at the proxy; set `SESSION_COOKIE_SECURE=1`. |
| **Bind address** | Set `HOST=127.0.0.1` so only the proxy can reach the app. |
| **No CSRF protection** | Verified: the app has no CSRF tokens; protection relies on `SameSite=Lax` cookies only. Admin actions and login accept form POSTs. **Do not expose the admin UI to untrusted networks** without a compensating control (VPN, IP allow-list, SSO at the proxy). |
| **Unauthenticated endpoint** | `POST /api/set-lang` is the only route without `@login_required` (sets UI language in session). Low risk, but be aware. |
| **Upload limits** | Enforced by `MAX_UPLOAD_MB` (app, 413) and `client_max_body_size` (proxy). Only `.jpg/.jpeg/.png/.webp/.pdf/.txt/.docx` are accepted; files are stored under server-generated UUID names (no path traversal). |
| **File permissions** | `chmod 600 .env` (holds API keys). Restrict `uploads/`, `paddleocr.db`, and `models/` to the service user. |
| **Run as non-root** | Use the dedicated `smartdocs` service user. |
| **Outbound traffic** | Cloud LLMs (Groq/Gemini/OpenAI/OpenRouter) and online translation need egress. Set `OFFLINE=1` and omit provider keys for a fully air-gapped deployment (agent then uses Local Qwen only). |
| **Tenancy** | Document/file access is ownership-checked server-side and RAG retrieval is scoped to the caller's files; the agent injects scope (the LLM cannot choose it). No action needed, but don't disable these checks. |

---

## 7. Backup considerations

What holds durable state:

| Data | Location | Backup method |
|---|---|---|
| Database (users, documents, **OCR/translation/summary artifacts**, chat + agent history) | `paddleocr.db` (or `DB_PATH`) | Consistent snapshot: `sqlite3 paddleocr.db ".backup '/backups/smartdocs-$(date +%F).db'"`. Avoid plain `cp` while running. |
| Uploaded files | `uploads/` (or `UPLOAD_DIR`) | Back up **together with the DB** — `documents.file_id` references these files; restoring one without the other leaves dangling rows/files. |
| Secrets / config | `.env` | Store securely (secret manager); not in VCS (`.gitignore` excludes it). |
| Local models | `models/` (or `MODEL_DIR`) | Large but static; back up once, or re-download via `scripts/setup_offline.sh` / `download_chat_model.py` / `warmup_modern_models.py`. |

Notes:
- The **in-memory RAG index is ephemeral** — it is rebuilt from DB artifacts on startup
  (via `wsgi.py`/`app.py`), so it needs no backup.
- For a quick consistent full backup, stop the service, copy `paddleocr.db` + `uploads/`,
  then start it again.

---

## 8. Health checks & smoke test

```bash
# App is up (login page should return 200; / redirects to /login when unauthenticated)
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/login        # 200

# GLM engine (only if deployed; Apple Silicon): MLX server reachable
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/chat/completions \
  -X POST -H "Content-Type: application/json" \
  -d '{"model":"mlx-community/GLM-OCR-bf16","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],"max_tokens":3}'   # 200
```

Then log in, upload a small image, run OCR, and confirm an artifact appears in the Document
Library. Validate the deeper checklist in [INSTALLATION.md §8](./INSTALLATION.md).

---

## 9. Known limitations affecting operations

- **Single process / single worker** → throughput is bounded; suitable for a team/internal
  tool, not high-concurrency public traffic.
- **First request latency**: models load lazily/in the background; the first chat or
  summarize call may return HTTP **202 "warming up"** until the model is ready.
- **GLM-OCR** requires a separate always-on MLX server (Apple Silicon). On Linux/Windows it
  is **UNKNOWN / unsupported** here; rely on the other three engines.
- **GPU PaddlePaddle** package/version for CUDA servers is **UNKNOWN** in this repo — consult
  the PaddlePaddle install matrix for your CUDA version.
