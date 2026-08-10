# Deploying the full stack for free on an Oracle Cloud Always Free VM

This runbook deploys the complete stack — app, worker, MySQL, Redis, Prometheus,
Alertmanager, Grafana, Loki/Promtail, Jaeger — onto a single always-free VM, behind
automatic HTTPS on a free subdomain.

**Why this host.** No managed free tier (Render, Fly, Railway) offers a free MySQL plus
nine long-running containers. Oracle's Always Free Ampere A1 allocation — 4 ARM cores,
24 GB RAM, 200 GB of block storage, no time limit — runs the existing compose stack
unchanged. All images used are multi-arch and have `linux/arm64` builds.

**The trade.** You own the machine: patching, backups and uptime are yours. Budget about
half an hour a month. If that is unwelcome, the `k8s/` manifests and
`.github/workflows/cd.yml` remain the path to managed infrastructure.

Everything below is done once. Redeploys afterwards are `git pull` + one compose command.

---

## 1. Provision the VM

1. Sign up at [cloud.oracle.com](https://cloud.oracle.com). A card is required for identity
   verification; Always Free resources cannot incur charges. Stay on the Free Tier — do not
   upgrade to Pay As You Go.
2. **Create instance**:
   - Shape: **Ampere / `VM.Standard.A1.Flex`**, **4 OCPU, 24 GB memory**
   - Image: **Canonical Ubuntu 22.04** (aarch64 build)
   - Boot volume: 100 GB
   - Save the generated SSH private key — it cannot be downloaded again.

   > A1 capacity is frequently exhausted. "Out of host capacity" is the one real friction
   > point here; retry in a different availability domain, or pick a less busy home region.
   > The region cannot be changed after signup, so choose carefully.

3. **Networking → VCN → Security List → Ingress rules.** Allow TCP **22, 80, 443** from
   `0.0.0.0/0`. Add nothing else — the observability UIs are reached over SSH, not the
   internet.

## 2. Point a free subdomain at it

Register a name at [duckdns.org](https://duckdns.org) and set its IP to the instance's
public IP. Verify from your laptop before continuing — Let's Encrypt validates over HTTP
and will fail on a stale record:

```bash
dig +short yourname.duckdns.org   # must print the instance's public IP
```

## 3. Prepare the host

SSH in as `ubuntu`, then:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker ubuntu   # log out and back in for this to take effect
docker compose version           # must be v2.24.0 or newer, see step 5
```

### Firewall

Ubuntu images on Oracle ship an iptables `INPUT` chain that **rejects everything except
SSH**, independently of the VCN Security List. Both must allow the traffic. Docker also
bypasses UFW entirely, so edit iptables directly rather than using `ufw`:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo apt install -y iptables-persistent   # answer "yes" to save current rules
```

Forgetting this produces a site that times out despite a correct Security List — it is the
single most common failure in this setup.

### SSH hardening

In `/etc/ssh/sshd_config` set `PasswordAuthentication no` and `PermitRootLogin no`, then
`sudo systemctl restart ssh`. Enable automatic security patching:

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

## 4. Configure secrets

```bash
git clone <your-repo-url> ~/apimonitor && cd ~/apimonitor
cp .env.example .env
```

Generate every secret **on the server**. Never copy your local development `.env` to a
public host.

```bash
for v in SECRET_KEY MONITOR_API_KEY ADMIN_PASSWORD \
         MYSQL_ROOT_PASSWORD MYSQL_PASSWORD GRAFANA_ADMIN_PASSWORD; do
  echo "$v=$(openssl rand -base64 36 | tr -d '/+=' | head -c 48)"
done
```

Paste those into `.env`, then set:

```
APP_ENV=production
PUBLIC_HOSTNAME=yourname.duckdns.org
ACME_EMAIL=you@example.com
DATABASE_URL=mysql+pymysql://apimonitor:<MYSQL_PASSWORD>@mysql:3306/apimonitor
ADMIN_USERNAME=<pick something other than "admin">
CORS_ORIGINS=
```

Leave `CORS_ORIGINS` empty — the overlay sets it from `PUBLIC_HOSTNAME`. Then
`chmod 600 .env`.

> **Do not rotate `SECRET_KEY` alone, ever.** `ENCRYPTION_KEY` is derived from it when
> unset (`app/services/crypto.py`), so changing `SECRET_KEY` makes every stored provider
> API key undecryptable. Either set `ENCRYPTION_KEY` explicitly now, or treat `SECRET_KEY`
> as permanent.

`app/config.py::validate_security_settings` refuses to start in production if
`DATABASE_URL`, `SECRET_KEY`, `MONITOR_API_KEY`, `ADMIN_USERNAME` or `ADMIN_PASSWORD` is
missing, short, or left at a `change-me` default. A failed startup here is that check
doing its job — read the error.

## 5. Deploy

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Always pass both `-f` flags. Plain `docker compose up` silently picks up
`docker-compose.override.yml`, which sets `APP_ENV=development` and disables the strict
secret validation above.

> Requires **Compose v2.24+** for the `!override` tag the overlay uses to rebind ports.
> On an older version the port lists are *concatenated* instead of replaced and every
> service stays exposed on `0.0.0.0` — which is exactly the thing this overlay exists to
> prevent. Check `docker compose version` before the first deploy.

The first build takes roughly 10 minutes (the frontend and Python wheels are compiled for
ARM). Certificate issuance happens on Caddy's first start and takes a few seconds.

## 6. Verify

Run the exposure check **from your laptop**, not from the server — a scan run on the host
sees the loopback bindings and will look wrong.

```bash
nmap -Pn <public-ip>                   # expect only 22, 80, 443
nc -zv <public-ip> 3306                # must fail  (MySQL)
nc -zv <public-ip> 3000                # must fail  (Grafana)

curl -I https://yourname.duckdns.org/health    # 200, valid chain, HSTS present
curl -I http://yourname.duckdns.org/           # 308 -> https
curl -s -o /dev/null -w '%{http_code}\n' https://yourname.duckdns.org/docs      # 404
curl -s -o /dev/null -w '%{http_code}\n' https://yourname.duckdns.org/metrics   # blocked
```

On the server:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps      # all healthy
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs web
# ^ shows `alembic upgrade head` completing before uvicorn binds
```

Log in to the SPA with `ADMIN_USERNAME`, confirm the dashboard renders, and check
`logs worker` shows the Redis stream consumer running.

Finally reboot the VM. Everything should return via `restart: unless-stopped`, and Caddy
should reuse its stored certificate rather than requesting a new one — the `caddy_data`
volume exists for exactly this, since Let's Encrypt allows only five duplicate
certificates per week.

## 7. Reaching Grafana, Prometheus and Jaeger

They are bound to loopback and are not on the internet. Tunnel over SSH from your laptop:

```bash
ssh -L 3000:localhost:3000 \
    -L 9090:localhost:9090 \
    -L 16686:localhost:16686 \
    ubuntu@<public-ip>
```

Then open `http://localhost:3000` (Grafana), `:9090` (Prometheus), `:16686` (Jaeger).
Grafana's credentials are `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`.

## 8. Backups

The MySQL volume is the only stateful thing that matters. A nightly dump:

```bash
mkdir -p ~/backups
crontab -e
```

```cron
0 3 * * * cd ~/apimonitor && docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec -T mysql mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" apimonitor \
  | gzip > ~/backups/apimonitor-$(date +\%F).sql.gz && \
  find ~/backups -name '*.sql.gz' -mtime +14 -delete
```

Copy them off the box periodically — a backup that only exists on the machine it protects
is not a backup. Restoring is untested until you test it; do that once.

## Redeploying

```bash
cd ~/apimonitor && git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Migrations apply automatically on container start.

## Known caveats

- **Idle reclamation.** Oracle documents reclaiming Always Free compute that stays idle.
  This stack's schedulers (`app/jobs/scheduler.py`) keep CPU above the threshold in
  practice, but it is policy, not a guarantee.
- **Single host.** No redundancy. A VM failure is downtime, and `k8s/redis.yaml` already
  notes Redis has no persistence — queued-but-unprocessed ingest events are lost on a
  Redis restart.
- **HSTS.** `app/main.py` sends a one-year `Strict-Transport-Security` header. Once a
  browser sees it, that hostname is HTTPS-only for a year. Correct here, but do not reuse
  the hostname for a plain-HTTP experiment afterwards.
