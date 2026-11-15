# AWS Monitor

AWS Monitor is a Flask dashboard for EC2 instances, VPCs, Application/Network
Load Balancers (ELBv2), and AMIs owned by the configured AWS account. It queries
one AWS region, displays cached inventory with freshness indicators, and protects
dashboard access with MongoDB-backed HTTP Basic authentication.

The repository includes Docker packaging, a Kubernetes Helm chart, and a Jenkins
pipeline for testing, security scanning, image publishing, and GitOps manifest updates.

## Repository layout

| Path | Purpose |
| --- | --- |
| `app/` | Flask application, dashboard assets, AWS fetching, and account management |
| `tests/` | Unit tests, Helm validation, and opt-in MongoDB integration tests |
| `Dockerfile`, `gunicorn.conf.py` | Container image and production server configuration |
| `chart/` | Kubernetes resources and configurable Helm values |
| `Jenkinsfile` | CI/CD stages using the external `aws-monitor-lib` shared library |
| `.github/workflows/ci-cd.yml` | GitHub Actions checks and manual environment releases |
| `.app-info.json` | Application metadata and separate Dev, QA, and Production versions |

## What Has Been Implemented

The repository provides the following DevOps components:

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

### GitHub Actions

`.github/workflows/ci-cd.yml` provides the GitHub Actions equivalent of the Jenkins
pipeline. Pull requests and pushes to `main` run application tests, Helm lint and
schema tests, Bandit, Checkov, and Semgrep. Tests run in the same Python/Alpine
image as the application; Helm tests also run on the host with Helm installed.
Live MongoDB integration tests remain opt-in and skip in this workflow.

To release, open **Actions > AWS Monitor CI/CD > Run workflow**, select `main`,
and choose `dev`, `qa`, or `prod`. Release jobs run only from `main`, after all
checks pass. Configure these GitHub Actions secrets at repository level or in
the corresponding GitHub environment:

| Secret | Purpose |
| --- | --- |
| `DOCKERHUB_USERNAME` | Docker Hub account allowed to publish the image |
| `DOCKERHUB_TOKEN` | Docker Hub access token with image push permission |
| `GITOPS_TOKEN` | Fine-grained token with Contents read/write access to the GitOps repository |

The built-in `GITHUB_TOKEN` updates `.app-info.json` in this repository. Repository
Actions settings and branch rules must permit that bot commit. Set up GitHub
environments named `dev`, `qa`, and `prod`; use required reviewers for production
if desired. Optional Actions variables `DOCKERHUB_REPOSITORY` and
`GITOPS_REPOSITORY` default to `sm1986/aws-monitor` and `StasX/argo-gitops`.

Release behavior follows the Jenkins shared library:

1. Read the selected version from `.app-info.json`.
2. Read `<environment>/values.yaml` from the GitOps `monitor` branch and overlay
   it on the current chart defaults. Render into the selected environment's namespace.
3. Validate the rendered manifest with Checkov, kube-score, and Trivy.
4. Build the Docker image and reject HIGH/CRITICAL vulnerabilities with Trivy.
5. Publish `<version>-dev`/`latest-dev`, `<version>-qa`/`latest-qa`, or production
   `<version>`/`latest` tags, preserving Jenkins tag naming.
6. Commit the manifest to `aws-monitor/<environment>/app.yaml` on GitOps `main`.
7. Increment only the selected environment's patch version in this repository.

Workflow artifacts are retained for 14 days and can be downloaded from the run's
**Artifacts** section:

- `test-reports`: application test output, Helm lint, and Helm schema test output.
- `security-reports-<scanner>`: Bandit, Checkov, and Semgrep text reports.
- `manifest-<environment>-<run>-<attempt>`: the rendered Helm manifest.
- `release-reports-<environment>-<run>-<attempt>`: rendered-manifest scan reports,
  Trivy JSON reports for the manifest and image, and the Docker build log.

Artifact uploads run even after a failed step, preserving reports produced before
the failure. Checks skipped after a failure do not produce reports. Logging through
`tee` preserves the original command's failure status through Bash `pipefail`, so
saving reports does not bypass release gates. Docker images are published to Docker
Hub; they are not duplicated as downloadable image archives.

GitOps performs
cluster reconciliation; the workflow does not run `kubectl apply` or `helm upgrade`
and needs no AWS or Kubernetes credentials. Scanners fail the pipeline on findings;
no scan failures are suppressed. Fix any reported findings before releasing.

Releases are serialized across environments, and a release stops before publishing
if application `main` has changed since it started. Publishing images and updating
two repositories are separate operations: if a later push fails, inspect the Docker
tags, GitOps commit, and metadata before retrying. No force pushes are used.
Metadata-only pushes do not trigger this workflow. The Jenkinsfile remains available;
disable its release job when switching to Actions so the two systems do not release
the same version concurrently.

### Jenkins Pipeline

The Jenkins pipeline runs on a Kubernetes agent with separate tool containers.

Pipeline stages include:

- Source code checkout.
- Application tests using unittest, blocking image builds and publishing on failure.
- Application version detection.
- Static code analysis.
- Security scanning.
- Docker image build.
- Docker image publishing.
- Helm manifest generation and validation.
- GitOps repository update.
- Application patch-version update in this repository.

Manifest generation, publishing, and version updates delegate to the external
shared library. The checked-in Jenkinsfile has no direct `helm upgrade` or
`kubectl apply` step; cluster reconciliation depends on your GitOps setup.

The `Application Tests` stage runs the full unittest suite in a dedicated container
matching the Dockerfile's Python/Alpine runtime. It installs `requirements.txt`
in an isolated virtual environment and has a ten-minute timeout covering setup
and execution. Tests mock AWS and require no AWS credentials. Helm tests skip
when Helm is unavailable (including in the dedicated Python test container);
live MongoDB tests skip unless `MONGODB_TEST_URI` is configured.

Jenkins also archives `reports/**/*.txt` and `manifests/app.yaml` in an
**Archive Artifacts** stage inside a `finally` block. Reports include application
tests, Bandit, Checkov, Semgrep, Trivy image/manifest scans, kube-score output,
and the Docker build log.
Reports produced before a failure are available from the build's **Artifacts**
section; skipped stages produce no report. Output is captured to a file and then
printed to the console, preserving the command's exit status so failed checks
still block publishing. Credential-bearing login commands are not captured.
Archives are fingerprinted and retained according to the Jenkins job's build and
artifact retention settings. Archiving requires the agent workspace to remain
available; a lost Kubernetes agent can prevent the final stage from running.

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
- Helm manifest generation.
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
- **kube-score** – Generated Kubernetes manifest checks.

## Application structure and local development

The Flask application uses a layered structure:

```text
app/
  app.py                       # Application setup and blueprint registration
  views/resources_view.py      # Dashboard route
  views/monitoring_view.py     # Health and metrics routes
  facades/resources_facade.py  # Dashboard orchestration
  logic/resources_logic.py    # AWS response transformations
  logic/resources_cache.py    # Shared clients, concurrent refresh, result caching
  logic/resource_worker.py    # Reusable isolated processes and enforced deadlines
  logic/users_logic.py        # Authentication and account lifecycle rules
  models/user.py              # User fields, validation, document conversion
  repositories/user_repository.py # MongoDB persistence for User models
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

Use Python 3.14 to match the container runtime. For an isolated local environment:

```sh
python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install -r requirements.txt
# Windows PowerShell:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Activate the virtual environment or use its Python executable for subsequent
commands. Configure MongoDB and create a dashboard user as described below, then
start `python -m app` and open `http://127.0.0.1:5001`.

The AWS identity needs these inventory permissions:

| Resource | IAM action |
| --- | --- |
| EC2 instances | `ec2:DescribeInstances` |
| VPCs | `ec2:DescribeVpcs` |
| Load balancers | `elasticloadbalancing:DescribeLoadBalancers` |
| Owned AMIs | `ec2:DescribeImages` |

The dashboard does not modify AWS resources. Search filters the inventory already
loaded in the browser. Reload the page to request fresh data; the age indicators
and removal of expired data update automatically without fetching new inventory.

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
| `APP_PORT` (Gunicorn) | 5001 | 1–65535 (integer) |

Zero disables result caching or the failure cooldown, or makes the HTTP refresh
wait return immediately. The background task budget must remain positive.

Docker runs Gunicorn using `gunicorn.conf.py`, listening on port 5001 with two
workers and four request threads per worker. Set `WEB_CONCURRENCY` and
`GUNICORN_THREADS` to tune concurrency, `APP_HOST` to change the bind address,
and `APP_PORT` to change the Gunicorn listening port. Helm sets `APP_PORT` from
`pod.targetPort`, keeping the listener, Service, and probes aligned. Docker's
health check also uses `APP_PORT`; publish the matching container port when
overriding it. The local development server still defaults to port 5001.
Access and error logs go to container output; worker heartbeat files use
`/dev/shm` to support the Helm deployment's read-only root filesystem.
On Linux, you can also run `gunicorn --config gunicorn.conf.py 'app.app:create_app()'`.
Use `python -m app` for local development on Windows.

Run the application tests with `python -m unittest discover -s tests -v`.
They mock the AWS session and do not require AWS credentials.

## Dashboard authentication

The dashboard uses HTTP Basic authentication (a browser login prompt) with
accounts stored in MongoDB's `users` collection. Configure `MONGODB_URI` and
`MONGODB_DATABASE`, then create an account using the commands below. Each user
has a unique, case-sensitive username (`_id`), a salted scrypt `password_hash`,
an `active` flag, and creation/update timestamps. Plaintext passwords are never
stored. All enabled users can view the dashboard.

Account code separates responsibilities: `models.User` represents an account and
converts MongoDB documents; `UserRepository` reads and writes those models;
`UsersLogic` applies password policy, verifies credentials, and manages account
changes. The HTTP authentication middleware and user CLI call the logic layer.
User documents retain their existing fields, so this structure requires no
database migration.

Missing or incorrect credentials, unknown users, and disabled accounts receive
the same HTTP 401 response before any AWS query. MongoDB failures return HTTP 503.
`/health`, `/metrics`, and static assets remain public. Dashboard responses use
`Cache-Control: no-store`. There are no default accounts or public registration
routes. Account changes are checked on each authenticated request, so password
resets and account disabling take effect on the next request without restarting
pods. A browser may prompt again after its saved password is changed.

Failed logins are throttled by source address: five failed or concurrent password
checks per 60-second window by default. Further attempts return HTTP 429 with
`Retry-After` before password hashing or AWS access. Successful requests refund
their slot, but do not erase earlier failures. An initial request without an
Authorization header receives the browser challenge without consuming a slot.
Malformed Authorization headers do count. Once blocked, even a correct password
must wait for the window to expire. Health and metrics remain accessible.

Set `dashboard.maxFailures` (1–100) and `dashboard.windowSeconds` (1–3600) in Helm,
or `AUTH_MAX_FAILURES` and `AUTH_WINDOW_SECONDS` in the environment. Both settings
are integers and are validated by Helm and the application.

All workers and pods share the throttle through MongoDB Atlas. Set `MONGODB_URI`
from a Kubernetes Secret and use the same `mongodb.database`, limits, and window
across replicas. Database updates reserve a slot atomically, using MongoDB's
clock so pod clock differences do not affect the window. Successful requests
refund only their original window. A TTL index removes expired records; expiry
is checked during reservation, independently of the background TTL cleanup.
The `auth_attempts` collection stores a hash of the source address, the counter,
and timestamps. The separate `users` collection stores account names and password
hashes. AWS credentials and plaintext passwords are not stored in either collection.

There is no SQLite or per-pod fallback. Missing configuration or database failure
blocks credential-bearing dashboard requests with HTTP 503. Health and metrics
stay available, and MongoDB connections are created lazily on the first login
attempt. Connections and operations have bounded timeouts and each worker uses
a pool capped at five connections per MongoDB server. Use separate databases for
independent environments; sharing a database intentionally shares their budget.

### MongoDB Atlas setup

1. Create your cluster through [MongoDB Atlas](https://www.mongodb.com/docs/atlas/driver-connection/).
2. Create a database user with `readWrite` on `aws_monitor` (or your configured
   database), allowing access to `users` and creation of `auth_attempts` and its TTL index.
   This Atlas database user is separate from dashboard accounts.
3. Add your Kubernetes cluster's outbound public/NAT IP addresses to Atlas Network
   Access. For local development, allow your local outbound public IP as well.
4. In Atlas, select **Connect > Drivers > Python** and copy the `mongodb+srv://`
   URI. Replace its username/password placeholders, URL-encoding special
   characters in credentials. Keep TLS certificate verification enabled.
5. Create the Kubernetes Secret before upgrading the release. This interactive
   command keeps the URI out of shell history and writes no local secret file:

```sh
python -c "import json; from getpass import getpass; print(json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':'aws-monitor-mongodb','namespace':'dev'},'type':'Opaque','stringData':{'MONGODB_URI':getpass('MongoDB Atlas URI: ')}}))" | kubectl apply -f -
```

The namespace must already exist. Configure `mongodb.existingSecret` if using
another Secret name, and `mongodb.database` if using another database. The
Secret must have a `MONGODB_URI` key. Do not put the URI in chart values, Git,
command-line `--set` arguments, or logs. Restart the Deployment after changing it.
The chart uses your hosted cluster; it does not deploy MongoDB in Kubernetes.

The NetworkPolicy allows outbound TCP 27017 for Atlas, alongside DNS and HTTPS.
Other cluster firewalls must also permit this connection; see
[Atlas connection troubleshooting](https://www.mongodb.com/docs/atlas/troubleshoot-connection/).

For local development, set `MONGODB_URI` before starting the app. In PowerShell,
you can enter it without putting the value in command history:

```powershell
$env:MONGODB_URI = python -c "from getpass import getpass; print(getpass('MongoDB Atlas URI: '))"
$env:MONGODB_DATABASE = 'aws_monitor'
```

Unit tests mock MongoDB and require no cluster credentials. For real database
validation, point `MONGODB_TEST_URI` at a **disposable test instance** and run:

```sh
python -m unittest discover -s tests -p test_mongodb_integration.py -v
```

These opt-in tests create randomly named `aws_monitor_test_*` databases and drop
only those databases afterward. The test user needs permission to create and drop
them. They verify concurrent clients sharing one budget, TTL-independent expiry,
refunds that cannot change a newer window, and account changes visible to
other clients. Never use production credentials.

By default the source is the connection's `request.remote_addr` and forwarding
headers are ignored. Behind an ingress, configure `dashboard.trustedProxyCidrs`
with the actual ingress source IP networks as seen by the app, for example:

```yaml
dashboard:
  trustedProxyCidrs:
    - 10.20.0.0/24
```

Replace the example with your proxy networks. Outside Helm, set
`AUTH_TRUSTED_PROXY_CIDRS` to comma-separated IPv4/IPv6 networks. Invalid networks
fail application startup. The default empty list trusts no proxies.
Only connections from these networks can supply `X-Forwarded-For`. The app walks
the chain from right to left through trusted proxies and uses the first untrusted
address as the throttle source. Missing or malformed chains use the connection
address. Each trusted proxy must append the actual connecting address or overwrite
the header with a verified client address. Trust only proxy source networks, never
all addresses or networks containing untrusted clients. Ensure any upstream load
balancer preserves client identity and configure the ingress's own forwarding
trust accordingly. Clients sharing a NAT still share a budget.

### Create and manage dashboard users

After configuring the MongoDB connection, create your first account from the
project directory:

```sh
python -m flask --app app users create operator
```

The command prompts for a password twice without displaying it or accepting it
as a command-line argument. Use 15–1024 characters. Usernames support 1–128
printable characters, are case-sensitive, and cannot contain colons or
surrounding whitespace. An existing username is rejected rather than overwritten.
Password hashing uses [Werkzeug scrypt](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash).

You can also run the command inside an already deployed pod, using the MongoDB
Secret configured for that release:

```sh
kubectl -n dev exec -it deployment/aws-monitor-deploy -- /app/env/bin/python -m flask --app app users create operator
```

Adjust the deployment name for your Helm release. Admin commands require access
to the MongoDB connection credentials; they are not exposed over HTTP. To manage
existing users:

```sh
python -m flask --app app users set-password operator
python -m flask --app app users disable operator
python -m flask --app app users enable operator
```

Password resets prompt for confirmation and preserve a disabled account's state.
Resetting or enabling an account does not clear an active source-address throttle;
wait for the retry window before logging in again. Use the dashboard browser
prompt to log in with the username and password you created.

Existing deployments must create their users in MongoDB before switching to this
version. The old `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD_HASH` environment
settings and `dashboard.existingSecret` Helm value have been removed. Remove that
old value from custom values files (including when using `--reuse-values`); the
Deployment now requires only the MongoDB connection Secret for authentication.
There is no automatic import or environment-credential fallback.

The Service type follows `ingress.enabled`:

| Configuration | Service type | Remote access |
| --- | --- | --- |
| `ingress.enabled=true` | `ClusterIP` | Through your ingress controller with the configured TLS Secret |
| `ingress.enabled=false` (chart default) | `LoadBalancer` | HTTP unless transport security is configured outside this chart |

Choose either option in `chart/values.yaml` or a release values file. The defaults
remain direct LoadBalancer access with no trusted proxies:

```yaml
ingress:
  enabled: false
dashboard:
  trustedProxyCidrs: []
```

For direct LoadBalancer access, throttling uses the connection's source IP.
A TCP load balancer does not supply `X-Forwarded-For`; adding trusted proxy
networks cannot recover a client IP lost through address translation. If multiple
clients reach the app with the same source IP, they share the login budget.

For access through an ingress, configure its hostname, existing TLS Secret,
and trusted source networks:

```yaml
ingress:
  enabled: true
  host: monitor.example.com
  tlsSecretName: aws-monitor-tls
dashboard:
  trustedProxyCidrs:
    - 10.20.0.0/24 # Example only: replace with your ingress source network.
```

The same options apply to Docker Desktop Kubernetes. Client-specific throttling
through ingress requires the ingress to receive and forward the client IP;
Docker Desktop or another upstream network layer may translate the source
address before it reaches the ingress. Verify the actual source network and
forwarded addresses in your environment before configuring trust. Direct
`kubectl port-forward` access does not add an HTTP forwarding header.

For an ingress deployment, explicitly enable ingress in the release values; using
an ingress controller in the cluster alone does not change this chart's Service
type. To expose the dashboard through ingress, point your hostname at
the ingress controller, create a TLS Secret containing a certificate for that
hostname, and set all three ingress values:

```sh
kubectl -n dev create secret tls aws-monitor-tls --cert=fullchain.pem --key=privkey.pem
helm upgrade --install aws-monitor ./chart --namespace dev --set pod.tag=YOUR_IMAGE_TAG --set ingress.enabled=true --set ingress.host=monitor.example.com --set ingress.tlsSecretName=aws-monitor-tls
```

The chart rejects enabled ingress without a host or TLS Secret name. The ingress
TLS host matches its routing host, following [Kubernetes ingress TLS configuration](https://kubernetes.io/docs/concepts/services-networking/ingress/#tls).
NGINX HTTPS redirect annotations are enforced. Other ingress controllers need their
own redirect configuration through `ingress.annotations`. Use HTTPS for remote
access: Basic authentication sends credentials with each request. Local HTTP is
intended for loopback development or a loopback port-forward only. The chart
references an existing certificate Secret; it does not issue certificates.

## Helm deployment configuration

Configure runtime settings under `app` in `chart/values.yaml`. These map directly
to the application's existing environment variables:

| Helm value | Environment variable | Default |
| --- | --- | --- |
| `app.awsRegion` | `AWS_REGION` | `us-east-1` |
| `app.cacheTtl` | `AWS_CACHE_TTL` | `30` |
| `app.refreshTimeout` | `AWS_REFRESH_TIMEOUT` | `3` |
| `app.failureCooldown` | `AWS_FAILURE_COOLDOWN` | `10` |
| `app.taskTimeout` | `AWS_TASK_TIMEOUT` | `15` |
| `app.maxDataAge` | `AWS_MAX_DATA_AGE` | `900` |
| `app.workers` | `WEB_CONCURRENCY` | `2` |
| `app.threads` | `GUNICORN_THREADS` | `4` |

Time settings use seconds and follow the validation ranges documented above.
`chart/values.schema.json` checks runtime setting types and ranges, port ranges,
and positive replica counts during Helm lint, template, install, and upgrade.
Use YAML numbers for numeric settings; numeric strings are rejected. Unknown
keys under `app` are rejected to catch typos. Application startup validation
remains in place for deployments outside Helm.
For fractional command-line values, use `--set-json app.taskTimeout=0.5`;
Helm's `--set` treats decimals as strings.
Override values per environment with a values file or, for example,
`--set app.awsRegion=eu-west-1 --set app.workers=3`. The resource region is
independent of `externalSecret.region`, which selects the Secrets Manager region.
Increasing workers also increases the number of AWS child processes and memory
usage per pod.

For your ingress deployment, install with an explicit image tag, hostname, and
existing TLS Secret. Create the namespace, AWS and MongoDB Secrets, and TLS Secret
before running this command:

```sh
helm upgrade --install aws-monitor ./chart --namespace dev --set pod.image=sm1986/aws-monitor --set pod.tag=YOUR_IMAGE_TAG --set ingress.enabled=true --set ingress.host=monitor.example.com --set ingress.tlsSecretName=aws-monitor-tls
```

The default image is `sm1986/aws-monitor:latest`; override it for your registry and release.
Before deployment, create the Secret named by `awsSecretName` in the release namespace,
with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` keys. Alternatively, enable
`externalSecret.enabled` to create a SecretStore and ExternalSecret. This requires
the External Secrets Operator and AWS permissions configured for its controller.
The Secrets Manager value must contain those same two keys as JSON properties.
For temporary credentials, also add `AWS_SESSION_TOKEN` to the Kubernetes Secret;
the Deployment injects it when present and allows it to be absent for long-lived
credentials. When using External Secrets, set
`externalSecret.includeSessionToken=true` and include the `AWS_SESSION_TOKEN`
JSON property in Secrets Manager. Rotate all three values together and restart
the Deployment after updating the Secret, since environment variables do not
refresh in running pods.

Autoscaling requires the Kubernetes metrics server. `hpa.minReplicas` defaults to
two; when HPA is disabled, `replicas` controls the deployment size. The disruption
budget uses `pdb.maxUnavailable` (default one).

Ingress is disabled by default and uses the nginx class with a Prefix path and no rewrite when enabled. Configure
`ingress.annotations` and `ingress.pathType` for deployments requiring regex rewrites.
Readiness and liveness use HTTP GET checks against `/health` on the named `http` port, without authentication or AWS access.
`/health` returns `{"status":"ok"}` without contacting MongoDB or AWS, so a
successful probe does not confirm dashboard dependencies are available.
Pod security settings belong under `securityContext`, including optional UID/GID overrides.

`/metrics` exports Prometheus application metrics without credentials or AWS calls:

- `aws_monitor_http_requests_total` counts completed requests by HTTP method,
  route template, and status code, including rejected dashboard logins.
- `aws_monitor_http_request_duration_seconds` is a latency histogram by method
  and route template, with buckets, count, and sum.

Scrapes exclude themselves. Unmatched URLs share one label, and raw URLs, query
strings, credentials, and AWS resource identifiers are not used as labels.
Metrics describe HTTP traffic; AWS inventory is not fetched during scraping.

Gunicorn aggregates all workers using the Prometheus client's
[multiprocess mode](https://prometheus.github.io/client_python/multiprocess/).
Its configuration sets `PROMETHEUS_MULTIPROC_DIR` before loading the application,
creates the dedicated directory, and clears metric files on master startup.
Docker sets it to `/dev/shm/aws-monitor-prometheus`, which is writable with the
chart's read-only root filesystem. Worker restarts preserve counters; restarting
the Gunicorn master resets them. Do not share this directory between instances
or enable Gunicorn application preloading. For local `python -m app`, leave the
variable unset to use an in-memory registry. Metrics aggregate per pod, not
across Kubernetes replicas; Prometheus can sum across pod time series.

PodMonitor and ServiceMonitor are disabled by default. Install the Prometheus
Operator CRDs and enable one with `--set podMonitor.enabled=true` or
`--set serviceMonitor.enabled=true`. Monitor selectors default to the release
namespace; set `podMonitor.env` or `serviceMonitor.env` to override it, and set the
corresponding `release` value when required by your Prometheus selector.

## Technologies Used

- Python, Flask, and Gunicorn
- Boto3
- MongoDB and PyMongo
- Prometheus client
- Docker
- Kubernetes
- Helm
- Jenkins
- Jenkins Shared Library
- Trivy
- Checkov
- Semgrep
- Bandit
- kube-score

## Project Goals

This project demonstrates:

- Docker containerization best practices.
- Kubernetes application deployment using Helm.
- CI/CD automation with Jenkins.
- DevSecOps practices through automated security scanning.
- Reusable CI/CD pipelines using Jenkins Shared Libraries.
