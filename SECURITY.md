# Security Policy

## Reporting a vulnerability

Report suspected vulnerabilities privately. **Do not open a public issue** —
this project is deployed as security monitoring infrastructure, so a public
report is a disclosure against every running instance at once.

- Use [GitHub private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  on this repository, or
- email the maintainer listed in the repository metadata.

Please include the affected version or commit, a description of the impact, and
the steps needed to reproduce it. A proof of concept helps but is not required
to file.

### What to expect

| Stage | Target |
| --- | --- |
| Acknowledgement | 3 working days |
| Initial assessment with severity | 10 working days |
| Fix or documented mitigation for high/critical | 30 days |

If you do not hear back within the acknowledgement window, please follow up —
a missed report is far more likely than a deliberate silence.

We will credit reporters in the release notes unless you ask us not to.

## Supported versions

This project has not yet cut tagged releases. Security fixes land on `main`;
run the latest commit.

## Scope

In scope:

- The API service under `app/`
- The web UI under `frontend/`
- The deployment manifests under `k8s/`, `nginx/` and `docker-compose.yml`
- The default configuration in `.env.example`

Out of scope:

- Findings that require an already-compromised administrator account
- Denial of service through sheer request volume against an instance with no
  rate-limit configuration in front of it
- Vulnerabilities in third-party dependencies with no exploitable path through
  this codebase — report those upstream, though we do want to hear about them
- The `--enable-demo` router and `scripts/seed_demo.py`, which exist to
  generate deliberately insecure sample traffic and must never be enabled in
  production

## Deploying securely

The following are the settings most commonly got wrong. All are enforced or
defaulted safely, but they are worth checking on any instance you run:

- **`APP_ENV=production`** — enables strict secret validation at startup. The
  service refuses to boot on weak or placeholder secrets.
- **`SECRET_KEY`, `MONITOR_API_KEY`, `ADMIN_PASSWORD`** — must be explicitly
  set in production; auto-generated development values change on every restart.
- **`ENCRYPTION_KEY`** — encrypts stored third-party provider credentials. If
  unset it is derived from `SECRET_KEY`, which means rotating `SECRET_KEY`
  makes those credentials undecryptable.
- **`EXPOSE_API_DOCS`** — off in production. `/docs` and `/openapi.json` are
  unauthenticated by design in FastAPI and publish the full route map.
- **`ALLOW_QUERY_AUTH`** — leave off. The live views no longer need it; they
  authenticate with short-lived stream tickets instead.
- **`CORS_ORIGINS`** — in production only the origins you list are trusted.

## Handling of sensitive data

- Passwords are bcrypt-hashed; API keys and refresh tokens are stored as
  SHA-256 digests. None are recoverable.
- Third-party provider credentials are the one exception — they are encrypted
  with Fernet rather than hashed, because probing a connection requires
  replaying them. See `app/services/crypto.py`.
- Query-string parameters with credential-shaped names are redacted before any
  captured path is persisted (`app/services/pathutil.py`).
- Password reset tokens are never logged in production and never returned by
  the API; they travel only in the email body.
