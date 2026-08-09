# 005 — Plain Kubernetes manifests, and the observability stack shape

## Context

Two Phase 5/6 decisions that shape how this gets deployed and operated, and
that would otherwise only exist as an undocumented shrug in the repo layout.

The README had documented `/run/secrets/`-based config loading for
Kubernetes since before any K8s target existed. Something had to fill that
gap, and the choice of *what* (raw manifests, Kustomize, Helm) is not
reversible for free once people have deployments built on it.

Separately, Phase 6 added three observability components (Prometheus
alerting, OpenTelemetry tracing, Loki log shipping) whose integration points
are worth recording, particularly where they are knowingly incomplete.

## Decision

### Plain manifests + Kustomize, not Helm

`k8s/` contains ordinary YAML with a `kustomization.yaml`, applied via
`kubectl apply -k k8s/`.

* **Helm** buys templating and a release lifecycle. This application has one
  deployment shape with a handful of substitutions (image tag, replica
  count, secret names). Kustomize's overlays cover that without asking a
  reader to understand Go templating to see what will actually be applied,
  and `kubectl kustomize k8s/` renders the real output for review with no
  extra tooling installed.
* **Reversibility:** a Helm chart can be written later around these
  manifests; going the other way (recovering readable YAML from a chart) is
  the harder direction. Starting plain keeps that option open.
* The bundled single-replica `redis.yaml` is a **convenience default, not a
  production recommendation** — it has no PersistentVolume, so losing the
  pod loses queued ingest messages and momentarily resets rate-limit
  counters and scheduler leadership. All three self-heal, but queued events
  since the last commit are gone. The file says so at the top; production
  should point `REDIS_URL` at managed Redis.
* `secret.example.yaml` and `ingress.example.yaml` are deliberately excluded
  from `kustomization.yaml` so `apply -k` cannot ship placeholder
  credentials or a wrong hostname by accident. `migrate-job.yaml` is
  excluded too, because Job specs are immutable — re-applying without
  deleting first is a silent no-op, so it needs the explicit
  delete-then-apply the CD workflow does.

### Observability integration points

* **Alerting** routes through Alertmanager with the receiver URL injected
  from `ALERT_WEBHOOK_URL` at container start (same `sed`-substitution
  pattern docker-compose already used for Prometheus's `MONITOR_API_KEY`).
  It defaults to a local no-op sink so the stack starts clean out of the
  box, with alerts still visible in the Alertmanager UI — an empty receiver
  list would have discarded them invisibly instead.
* **A latency Histogram was added alongside the existing Counter.**
  `api_request_duration_seconds` is a Counter, which can only yield an
  average via `rate()`. p95/p99 alerting needs bucket data, hence
  `apimonitor_request_duration_seconds` as a Histogram. It is deliberately
  **unlabeled by path**: the existing per-path Counter already fans out to
  one series per (method, path, status), and multiplying that by a
  histogram's ~13 buckets per series is a cardinality problem waiting to
  happen on a system whose whole purpose is discovering unbounded numbers of
  new endpoints.
* **Tracing is inert without a collector.** `OTEL_EXPORTER_OTLP_ENDPOINT`
  unset means instrumentation still runs but the TracerProvider has no span
  processor, so spans are created and dropped. The alternative — attaching an
  exporter that can't reach anything — produces continuous
  connection-failure log noise in every dev environment.

## Consequences

**Good.** `kubectl apply -k k8s/` gives a working stack; the rendered output
is inspectable without extra tooling; the observability components all
degrade to no-ops rather than hard failures when unconfigured.

**Bad / accepted, and explicitly unverified.** None of the K8s manifests
have been applied to a live cluster — `kubectl kustomize` validates that
they *render*, which is a strictly weaker claim than that they *run*.
Likewise the CD workflow (`.github/workflows/cd.yml`) cannot function until
someone configures the `production` GitHub Environment's required-reviewers
rule and a `KUBE_CONFIG_PRODUCTION` secret; those are repo-settings and
cluster-access decisions that a workflow file cannot make for itself.

Promtail's Docker-log-file approach requires `/var/lib/docker/containers`
from the host, which does not work on Docker Desktop (the daemon runs inside
a VM). Documented in the README with the Loki Docker-driver-plugin
alternative; in Kubernetes a DaemonSet shipper replaces this entirely.

**Known gap.** Trace context is not propagated through the Redis ingest
queue, so an HTTP request and the worker processing its event are two
separate traces rather than one. Closing it means injecting the trace
context into the message payload on enqueue and extracting it on consume —
tracked, not done.
