# AWS Monitor

This project demonstrates the containerization, CI/CD automation, security scanning, and Kubernetes deployment of an existing Flask application that monitors AWS resources.

## What Has Been Implemented

The following DevOps components have been fully implemented:

### Docker

The application has been containerized using Docker.

Implemented features include:

- Base image package upgrades.
- Running the application as a non-root user.
- Container health check configuration.
- Docker image versioning.
- Automated Docker image publishing to Docker Hub.

### Helm

A reusable Helm chart has been created for Kubernetes deployments.

The chart includes:

- Configurable Docker image repository and tag.
- Replica configuration.
- Kubernetes Service.
- NGINX Ingress support.
- Kubernetes Secrets integration.
- Resource requests and limits.
- Multi-environment deployments (Dev, QA, Production).

### Jenkins Pipeline

A complete CI/CD pipeline has been implemented using Jenkins.

Pipeline stages include:

- Source code checkout.
- Application tests using unittest, blocking image builds and publishing on failure.
- Application version detection.
- Static code analysis.
- Security scanning.
- Docker image build.
- Docker image publishing.
- Helm chart deployment.
- GitOps repository update.
- Kubernetes deployment.

The `Application Tests` stage runs the full unittest suite in a dedicated container
matching the Dockerfile's Python/Alpine runtime. It installs `requirements.txt`
in an isolated virtual environment and has a ten-minute timeout covering setup
and execution. Tests mock AWS and require no AWS credentials.

### Jenkins Docker daemon isolation

Builds, image scans, tagging, and publishing run inside the `docker` container
using `unix:///var/run/docker.sock`. The pipeline starts `dockerd` directly with
only that Unix socket, bypassing the image entrypoint's automatic TCP listeners.
The socket is not mounted into the other containers. Docker storage uses a
pod-scoped `emptyDir`; no host Docker socket or host Docker data directory is
mounted. A bounded readiness check waits for the daemon before pipeline work.

The Docker-in-Docker container still runs privileged. A local socket removes
network access to the daemon, but does not remove the node risk of privileged
builds. Run this agent on dedicated, disposable CI nodes, restrict who can submit
pipeline code, and do not schedule untrusted pull requests or production workloads
on those nodes. Removing privileged mode requires migrating the build and scan
steps in the shared library to a compatible builder.

### Jenkins Git certificate trust

Checkout verifies HTTPS certificates using the agent's trusted certificate
authorities by default. For an internal Git server or TLS inspection proxy,
create a Jenkins **Secret file** credential containing a PEM CA bundle and set
the job environment variable `GIT_CA_CREDENTIALS_ID` to its credential ID.
Include the required root and intermediate CA certificates, plus public roots
if checkout also accesses public repositories. The pipeline binds this file as
`GIT_SSL_CAINFO` only during checkout and explicitly enables TLS verification.
An invalid or untrusted certificate fails checkout.

The Jenkinsfile cannot configure trust for its own initial retrieval or for the
Shared Library, which loads before pipeline execution. Configure the same CA
trust on the Jenkins controller and relevant agents for those operations. GitOps
operations in the separate `git` container also need the CA in that container's
trust store when accessing internal servers. Remove any legacy global
`http.sslVerify=false` configuration from Jenkins agent images and configuration.

### Jenkins Shared Library

The Jenkins pipeline uses a reusable Shared Library to centralize common pipeline functionality, including:

- Project metadata loading.
- Docker image version management.
- Security scan execution.
- Helm deployment automation.
- GitOps repository updates.
- Shared pipeline utilities.

Shared Library Repository:

https://github.com/StasX/aws-monitor-lib

### Automated Security Scanning

The pipeline automatically performs security and quality analysis using:

- **Semgrep** – Static Application Security Testing (SAST).
- **Bandit** – Python security analysis.
- **Checkov** – Infrastructure as Code (IaC) security scanning.
- **Trivy** – Container image vulnerability scanning.

## Application structure and local development

The Flask application follows the layered structure of the
[vacations-agency Flask app](https://github.com/StasX/vacations-agency/tree/main/Flask):

```text
app/
  app.py                       # Application setup and blueprint registration
  views/resources_view.py      # Dashboard route
  views/monitoring_view.py     # Health and metrics routes
  facades/resources_facade.py  # Dashboard orchestration
  logic/resources_logic.py    # AWS response transformations
  logic/resources_cache.py    # Shared clients, concurrent refresh, result caching
  logic/resource_worker.py    # Reusable isolated processes and enforced deadlines
  utils/dal.py                # Boto3 data access
  utils/app_config.py         # Environment configuration
  templates/layout.html      # Shared HTML layout
  templates/index.html       # Resource tables
```

The request flow is view → facade → logic → DAL. AWS clients are created only
for dashboard requests, so health and metrics checks do not require credentials.
Run locally with `python -m pip install -r requirements.txt`
followed by `python -m app` (port 5001), or use `python -m flask --app app run --port=5001`.
AWS credentials use the standard Boto3 credential chain; `AWS_REGION` defaults to
`us-east-1`.

Successful resource sections are cached for 30 seconds per application worker.
Set `AWS_CACHE_TTL` to change this duration, or to `0` to disable result caching.
Refreshes fetch resource types concurrently and reuse AWS clients. Failed sections
show an error and wait `AWS_FAILURE_COOLDOWN` seconds (default 10) before a later
visit can retry. Set it to `0` to disable the cooldown. Previously fetched data
remains visible with a warning during failures. A request initiating a refresh waits at
most `AWS_REFRESH_TIMEOUT` seconds (default 3). Visits reuse running queries while
independently refreshing other expired sections or retrying sections whose cooldown
has ended. Requests only wait for queries they start, showing previous data with a warning, or an unavailable
message if no previous data exists. Requests use a bounded pool of four supervisors
to manage reusable resource processes; the HTTP wait limit does not cancel them.
AWS clients use short connection/read timeouts and bounded retries.
Each resource fetch also has an `AWS_TASK_TIMEOUT` budget (default 15 seconds),
covering process startup, AWS calls, and pagination. Each resource type runs in its
own spawned process. A supervisor terminates that process when the deadline is
reached, including an in-flight SDK call, discards incomplete results, and applies
the failure cooldown. The next attempt starts a fresh process for that section.
Successful processes remain alive and reuse their AWS sessions and clients.
There can be up to four child processes per application worker, so account for
their memory usage when choosing Gunicorn concurrency. Processes are created only
for dashboard queries; health and metrics endpoints do not start them.
Each section shows the UTC time of its last successful fetch and its age. Ages
advance in the browser without reloading. Failed refreshes retain that original
timestamp and mark previous results as stale, including previously empty results.
A section that has never loaded successfully is labeled accordingly.
Results are removed once they reach `AWS_MAX_DATA_AGE` (default 900 seconds),
even if the normal cache TTL is longer. The dashboard retains the fetch timestamp
and displays an expired-data message until a refresh succeeds. Open browser pages
also remove expired rows and counts automatically. The cache releases expired
payloads when accessed, retaining only their fetch metadata.
Cached data and clients are not shared
between worker processes or Kubernetes replicas. Restart the app after changing
environment credentials or static configuration.

Numeric settings are validated at startup. Invalid text, NaN, infinity, fractions
for integer settings, and values outside these inclusive ranges are rejected with
the setting name and allowed range:

| Setting | Default | Allowed range |
| --- | --- | --- |
| `AWS_CACHE_TTL` | 30 seconds | 0–86400 seconds |
| `AWS_REFRESH_TIMEOUT` | 3 seconds | 0–30 seconds |
| `AWS_FAILURE_COOLDOWN` | 10 seconds | 0–3600 seconds |
| `AWS_TASK_TIMEOUT` | 15 seconds | 0.1–300 seconds |
| `AWS_MAX_DATA_AGE` | 900 seconds | 1–86400 seconds |
| `WEB_CONCURRENCY` | 2 | 1–32 workers (integer) |
| `GUNICORN_THREADS` | 4 | 1–64 threads (integer) |

Zero disables result caching or the failure cooldown, or makes the HTTP refresh
wait return immediately. The background task budget must remain positive.

Docker runs Gunicorn using `gunicorn.conf.py`, listening on port 5001 with two
workers and four request threads per worker. Set `WEB_CONCURRENCY` and
`GUNICORN_THREADS` to tune concurrency, and `APP_HOST` to change the bind address.
Access and error logs go to container output; worker heartbeat files use
`/dev/shm` to support the Helm deployment's read-only root filesystem.
On Linux, you can also run `gunicorn --config gunicorn.conf.py 'app.app:create_app()'`.
Use `python -m app` for local development on Windows.

Run the application tests with `python -m unittest discover -s tests -v`.
They mock the AWS session and do not require AWS credentials.

## Helm deployment configuration

Install with an explicit image tag published by your pipeline:

```sh
helm upgrade --install aws-monitor ./chart --namespace dev --create-namespace --set pod.image=sm1986/aws-monitor --set pod.tag=YOUR_IMAGE_TAG
```

The default image is `sm1986/aws-monitor:latest`; override it for your registry and release.
Before deployment, create the Secret named by `awsSecretName` in the release namespace,
with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` keys. Alternatively, enable
`externalSecret.enabled` to create a SecretStore and ExternalSecret. This requires
the External Secrets Operator and AWS permissions configured for its controller.
The Secrets Manager value must contain those same two keys as JSON properties.

Autoscaling requires the Kubernetes metrics server. `hpa.minReplicas` defaults to
two; when HPA is disabled, `replicas` controls the deployment size. The disruption
budget uses `pdb.maxUnavailable` (default one).

Ingress defaults to the nginx class with a Prefix path and no rewrite. Configure
`ingress.annotations` and `ingress.pathType` for deployments requiring regex rewrites.
Readiness and liveness use TCP checks because the application has no health route.
Pod security settings belong under `securityContext`, including optional UID/GID overrides.

PodMonitor and ServiceMonitor are disabled by default: the current application
does not export Prometheus metrics. Enable one after implementing metrics and
installing the Prometheus Operator CRDs. Monitor selectors default to the release
namespace; set `podMonitor.env` or `serviceMonitor.env` to override it, and set the
corresponding `release` value when required by your Prometheus selector.

## Technologies Used

- Docker
- Kubernetes
- Helm
- Jenkins
- Jenkins Shared Library
- GitHub Actions
- Trivy
- Checkov
- Semgrep
- Bandit

## Project Goals

This project demonstrates:

- Docker containerization best practices.
- Kubernetes application deployment using Helm.
- CI/CD automation with Jenkins.
- DevSecOps practices through automated security scanning.
- Reusable CI/CD pipelines using Jenkins Shared Libraries.
