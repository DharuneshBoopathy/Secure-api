# Deploying to Hugging Face Spaces (free, no credit card)

The fastest way to get a public, working instance online. Roughly ten minutes,
most of it spent generating secrets.

**Why this and not a cloud VM.** Oracle, Google Cloud, AWS and Azure all require
a payment card for identity verification, even on tiers that never charge.
Hugging Face does not — an account is free and cardless, and the free CPU tier
gives 2 vCPU and 16 GB of RAM, which is more memory than the entire compose
stack reserves. It also builds in seconds here, because the Space wraps the
image CD already publishes rather than rebuilding the app.

**What you give up.** Storage is ephemeral, so the database resets on every
restart — this is a demo, not somewhere to keep data. It is a single container:
no Redis queue, no separate worker, no Prometheus/Grafana/Loki/Jaeger. Ingestion
processes inline and the scheduler runs in-process; both are supported
configurations rather than compromises, but the observability stack is simply
not part of this deployment. Free Spaces also sleep after inactivity and take a
few seconds to wake. For the full stack on a real host, see
[deployment-oracle-free.md](deployment-oracle-free.md).

---

## 1. Create the Space

Go to <https://huggingface.co/new-space> and set:

- **Owner**: `dharuneshboopathy`
- **Space name**: `api-security-monitor`
- **License**: MIT
- **SDK**: **Docker** → **Blank**
- **Visibility**: Public

## 2. Add the two files

The Space is a git repository. Copy both files from `deploy/huggingface/` in
this repo to the **root** of the Space:

```bash
git clone https://huggingface.co/spaces/dharuneshboopathy/api-security-monitor
cd api-security-monitor
cp /path/to/Secure-api/deploy/huggingface/Dockerfile .
cp /path/to/Secure-api/deploy/huggingface/README.md .
git add Dockerfile README.md
git commit -m "Run the released API Security Monitor image"
git push
```

Both belong at the root — the Space reads `README.md`'s YAML frontmatter for
`sdk: docker` and `app_port: 8000`. Without `app_port` the platform looks for a
service on 7860 and the Space never comes up.

You can also paste both files through the web editor (**Files → Add file**) if
you would rather not clone.

## 3. Set the secrets

**Settings → Variables and secrets → New secret**, four of them:

| Name | Value |
|---|---|
| `SECRET_KEY` | 32+ random characters |
| `MONITOR_API_KEY` | 32+ random characters |
| `ADMIN_USERNAME` | Anything but `admin` |
| `ADMIN_PASSWORD` | Strong — this instance is public |

Generate each with:

```bash
openssl rand -base64 36 | tr -d '/+=' | head -c 48; echo
```

Use **secrets**, not variables: variables are visible to anyone who opens the
Space. Do not reuse the values from your local `.env`.

> `SECRET_KEY` also derives `ENCRYPTION_KEY`, which encrypts stored provider
> credentials (`app/services/crypto.py`). Changing it later makes anything
> already encrypted unreadable. On an ephemeral demo that costs nothing, but
> the same rule bites hard on a real deployment.

The Space rebuilds and starts on its own after the last secret is saved.

## 4. Verify

Watch **Logs**. A healthy start shows Alembic applying migrations against the
SQLite file, then uvicorn binding to `0.0.0.0:8000`.

```bash
SPACE=https://dharuneshboopathy-api-security-monitor.hf.space

curl -s $SPACE/health                                 # {"status":"ok","db":"ok"}
curl -sI $SPACE | grep -i strict-transport-security   # HSTS present

# Confirm the API docs are withheld. Check the *body*, not the status code:
# unknown paths return 200 with the SPA shell, because a single-page app has
# to render its own 404s client-side. A disabled /docs therefore looks like a
# 200 too, and only the content distinguishes them.
curl -s $SPACE/openapi.json | grep -q '"openapi"' \
  && echo "SPEC IS EXPOSED — check EXPOSE_API_DOCS" \
  || echo "spec withheld, as expected"
```

Then open the Space and sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`. First
boot creates the bootstrap admin and a default organization. `ENABLE_DEMO=true`
is set in the Dockerfile so there is seedable data to look at.

**If the Space shows "Runtime error"**, open Logs and look for a `RuntimeError`
from `validate_security_settings` — that is the production guard reporting a
missing or too-short secret, and it names the one at fault.

## 5. Updating

The Space pulls `:latest`, so it does not track your commits automatically.
After CD publishes a new image, hit **Settings → Factory rebuild** to pick it
up. Pin a specific release instead by editing the Space's `Dockerfile`:

```dockerfile
FROM ghcr.io/dharuneshboopathy/secure-api:<commit-sha>
```

Remember that a rebuild wipes the database, since it lives in `/tmp`.
