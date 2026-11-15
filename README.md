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
- Application version detection.
- Static code analysis.
- Security scanning.
- Docker image build.
- Docker image publishing.
- Helm chart deployment.
- GitOps repository update.
- Kubernetes deployment.

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
