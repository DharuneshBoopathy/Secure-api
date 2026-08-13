# Deploying to Render (free, no payment card)

A public, working instance in about fifteen minutes, with no card and no cloud
account — and unlike the earlier draft of this guide, with a database that
survives redeploys.

**Live instance:** <https://api-security-monitor.onrender.com> — free plan,
Singapore, image-backed. It sleeps after 15 minutes idle, so the first request
after a quiet spell takes 30–60 seconds. Everything below is the procedure that
produced it, including the two mistakes it took to get there.

**Why here.** Oracle, Google Cloud, AWS and Azure all require a payment card for
identity verification even on tiers that never charge. Hugging Face Spaces looks
like an answer but is not: Gradio and Docker Spaces "require a paid plan to
create — PRO for personal accounts", and only Static Spaces are free, which
cannot run a backend. Render's free plan needs no card and gives 750
instance-hours a month, enough to keep one service up continuously.

**Not Railway.** Railway's Free plan grants $1 of usage credit per month. A
512 MB container running continuously costs roughly $5/month of usage there, so
the plan cannot keep this app alive for a full month; the $5 trial credit covers
about 25–30 days and then it stops. Railway is only an option once the budget
stops being zero.

**Measured, not assumed:** the released image was run locally under a hard
512 MB cap — the free plan's limit — and settled at **184 MiB after 120
requests**, with no OOM kill and no restarts. scikit-learn, pandas and numpy all
load inside the budget. Read the [memory](#memory) section before trusting that
number for the long run, though: it was measured against an empty database.

## What you give up

- **Sleeps after 15 minutes of inactivity**, then takes 30–60 seconds to wake.
  The first visitor after a quiet spell waits; everyone after that does not.
- **Single container.** No Redis, no separate worker, no
  Prometheus/Grafana/Loki/Jaeger. Ingestion runs inline instead of through the
  queue and the scheduler runs in-process — both supported modes, but the
  observability stack is not part of this deployment. Render's free plan does
  not offer background workers or cron jobs at all, so leave `REDIS_URL` and
  `OTEL_EXPORTER_OTLP_ENDPOINT` unset.
- **Single region.** Fine for a globally reachable demo; visitors far from the
  region pay 100–300 ms.

---

## 1. Create the database

Render's own free Postgres is not an option: it is **deleted 30 days after
creation** and cannot be renewed. This app also has no Postgres driver — it
pins `pymysql` and there is no `psycopg` in `requirements.lock` — so the
database is a free managed **MySQL** elsewhere. Nothing in the code changes.

**TiDB Cloud Starter** (recommended — 5 GiB, permanent free plan, no card,
MySQL wire protocol):

1. Sign up at <https://tidbcloud.com> with GitHub or Google.
2. Create a **Starter** cluster in **ap-southeast-1 (Singapore)**, matching the
   Render region below.
3. Create a database on it — `apimonitor` — rather than using the default
   `test`.
4. **Connect** → copy the host, port (4000), user (looks like `xxxxxxxx.root`)
   and the generated password.

Assemble the connection string. TiDB refuses non-TLS connections, so the SSL
parameters are not optional:

```
mysql+pymysql://<user>.root:<password>@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/apimonitor?ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_cert=true&ssl_verify_identity=true
```

That CA path is Debian's, which is correct because the image's runtime stage is
`python:3.12-slim`. Confirm rather than assume:

```bash
docker run --rm ghcr.io/dharuneshboopathy/secure-api:latest \
  ls -l /etc/ssl/certs/ca-certificates.crt
```

**Run the migrations from your machine first.** They have been exercised against
MySQL and SQLite but never against TiDB, and finding out here takes seconds
where finding out on Render costs a boot loop:

```bash
DATABASE_URL='mysql+pymysql://...' alembic upgrade head
```

Four revisions should apply. The baseline schema uses `mysql_length=` index
prefixes and a `mysql.LONGTEXT` variant, all of which TiDB accepts as
MySQL-compatible DDL.

*Alternative:* **Aiven for MySQL** free plan — 1 GB, free forever, no card. It
works, but Aiven powers a free service off after a stretch of inactivity and
needs a manual power-on, which pairs badly with an app that sleeps.

## 2. Create the service

1. Sign up at <https://render.com> with your GitHub account. No card.
2. **New → Blueprint**, then select the `Secure-api` repository.
3. Render reads [`render.yaml`](../render.yaml) from the repo root and shows one
   web service, `api-security-monitor`, on the free plan.
4. It prompts for the three values deliberately not stored in the repo:

   | Prompt | Value |
   |---|---|
   | `DATABASE_URL` | The connection string from step 1 |
   | `ADMIN_USERNAME` | Anything but `admin` |
   | `ADMIN_PASSWORD` | Strong — this instance is public |

   `SECRET_KEY`, `MONITOR_API_KEY` and `ENCRYPTION_KEY` are generated by Render,
   so you never handle them. Do not paste values from your local `.env`.
5. **Apply**. The service pulls the pinned image and starts; no build step,
   because CD already built it. The image is public on GHCR, so no registry
   credentials are needed.

## 3. Verify

Watch the deploy log: Alembic reports four migrations already at head, then
uvicorn binds. Render marks the service live once `/health` answers.

That "already at head" line is the durability check, and it is worth reading
every time. If Alembic *applies* four migrations on a boot that is not the
first one, it found an empty database — the service is running on storage that
did not survive the last spin-down, and every table went with it. The instance
will still look healthy, because `ensure_default_admin` recreates the admin
account on each boot and login keeps working; the audit log is usually the
first place anyone notices the loss.

```bash
APP=https://api-security-monitor.onrender.com   # replace if you renamed the service

curl -s $APP/health                                 # {"status":"ok","db":"ok"}
curl -sI $APP | grep -i strict-transport-security   # HSTS present

# Confirm the API docs are withheld. Check the body, not the status: unknown
# paths return 200 with the SPA shell so the app can render its own 404s, so a
# disabled /docs and a live one both answer 200.
curl -s $APP/openapi.json | grep -q '"openapi"' \
  && echo "SPEC IS EXPOSED — check EXPOSE_API_DOCS" \
  || echo "spec withheld, as expected"
```

Then open the URL and sign in with the admin credentials you set. First boot
creates the bootstrap admin and a default organization.

**Prove the persistence**, since that is the whole point of the external
database. Create some data, then **Manual Deploy**, then confirm it is still
there. Then leave it idle for 15+ minutes, wake it, and check once more.

**If the deploy fails immediately**, read the log for a `RuntimeError` from
`validate_security_settings` — that is the production guard naming a missing or
too-short secret. A hang followed by an `OperationalError` instead means
`wait_for_database` exhausted its ten retries: check the TLS parameters on
`DATABASE_URL` first.

Two of that guard's messages are about this section specifically:

| Message | Cause |
|---|---|
| `DATABASE_URL is not set` | The blueprint prompt was skipped or left blank. Set it under **Environment** and redeploy. |
| `DATABASE_URL points at SQLite …` | A SQLite URL was pasted, or copied from a local `.env`. SQLite lives inside the container and this plan has no disk, so it is refused rather than accepted and quietly discarded. |

Both are deliberate hard failures. A service that will not boot is recoverable
in a minute; a service that boots onto empty storage loses its audit trail and
says nothing.

### Do not add a dockerCommand

`render.yaml` deliberately sets none, and the reason is worth stating because
the obvious fix for `$PORT` is to add one. **Render splits `dockerCommand` into
argv and execs it directly — there is no shell**, so the `&&` that chains the
migration to the server never works. Both spellings were tried against the live
service:

| `dockerCommand` | Result |
|---|---|
| `sh -c "alembic upgrade head && uvicorn ..."` | `sh: 1: alembic upgrade head && uvicorn ...: not found`, exit 127 — the quoting does not survive Render's parser, so the whole string arrives as one command name |
| `alembic upgrade head && uvicorn ...` | `alembic: error: unrecognized arguments: && uvicorn ...`, exit 2 — no shell, so `&&` is just another argument |

With no override, the image's own `CMD` runs, and *that* chain works because
Docker gives it a real shell. `PORT=8000` makes Render route to the port the
image hardcodes, and `FORWARDED_ALLOW_IPS=*` replaces the `--forwarded-allow-ips`
flag (`--proxy-headers` is already uvicorn's default). Migrations still run on
every boot, which the ephemeral-SQLite path depends on.

## 4. Updating

**Image-backed services do not auto-deploy.** Render redeploys on push to `main`
for Git-backed services; this is not one, and `render.yaml` pins a commit sha
rather than `:latest` so that what is running stays legible.

CD is `workflow_dispatch`-only, so shipping a code change is three steps: run the
`cd.yml` workflow manually, update the `url:` tag in `render.yaml` to the new
sha, then **Manual Deploy** in Render. Redeploying no longer touches the
database.

## Memory

The 184 MiB figure above was measured against a database that was wiped on every
deploy — effectively an empty dataset. With a durable database the profile
changes, and this is the thing most likely to eventually exhaust a 512 MB
instance:

`run_bootstrap_training()` fits IsolationForest/LOF in a thread at startup, and
the `ml_retrain` job repeats it on a schedule. Each run builds a pandas
DataFrame from **every traffic event in the lookback window, per organization**.
On an empty database that is a no-op — `MIN_SAMPLES_GLOBAL` is never met — but
that DataFrame now grows with whatever accumulates.

`render.yaml` sets `ML_RETRAIN_MINUTES=60` rather than the default 15 for this
reason. The `prune_stale_traffic` job (every 12 h) and `ZOMBIE_WINDOW_DAYS`
bound retention. Watch Render's memory graph over the first few weeks rather
than treating 184 MiB as settled.

Separately, `/api/ingest/pcap` buffers uploads in memory up to `PCAP_MAX_BYTES`
(50 MB), a ~50–100 MB transient spike. Avoid large PCAP ingests here.

## Keeping it awake

Free services sleep. An uptime pinger hitting `/health` keeps it warm, at two
costs worth knowing before you set one up:

- 730 hours in a month against a 750-hour monthly allowance leaves almost
  nothing spare. One always-on service is the entire budget.
- `/health` touches the database (it returns `"db":"ok"`), so a frequent ping
  also stops the database from ever idling down, which spends the free
  database's compute budget as well as Render's.

If you want it warm anyway, ping every **14 minutes** — inside Render's
15-minute sleep threshold, while still leaving the database idle most of the
time. Otherwise leave it sleeping and accept the cold start.
