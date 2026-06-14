# CGIAR Innovation Analytics — AWS Deployment Architecture Proposal

**Date:** 2026-05-22
**Author:** AI-generated proposal for review
**Status:** Awaiting approval

---

## Executive Summary

I recommend deploying the CGIAR Innovation Analytics Platform using the same **EC2 + ALB + Docker** pattern proven by `sc-cgiar-agent`. This is the only pattern in our ecosystem that fully supports WebSocket connections, SQLite databases, and stateful agent sessions. The deployment will use OIDC-authenticated GitHub Actions CI/CD with multi-environment support (dev → staging → prod).

---

## 1. Investigation Findings

### 1.1 Existing Deployment Patterns

| Project | Architecture | AWS Service | Reason |
|---------|-------------|-------------|--------|
| `sc-cgiar-agent` | EC2 + Docker + ALB | Single EC2 instance | WebSocket + Claude Agent SDK + SQLite |
| `demand-intelligence-platform` | S3 + CloudFront | Static site | React-only, no backend |
| `synapsis-agent-macos-v23` (your infra) | EC2 Auto Scaling + Lambda orchestrator | Multi-instance ASG | Multi-tenant scaling |
| `evidence-scraper-serverless` | Lambda + Step Functions | Serverless | Event-driven pipeline |

### 1.2 Why EC2 + ALB (Not Fargate, Not App Runner)

| Requirement | EC2+ALB | ECS Fargate | App Runner |
|-------------|---------|-------------|------------|
| WebSocket support | Full (ALB sticky sessions, 4000s idle) | Full | Limited (no sticky sessions) |
| SQLite 398MB file | EBS volume, persistent | Ephemeral storage only (20GB max) | No persistent storage |
| Claude Agent SDK | Works (long-running process) | Works but task timeouts | 30-min request timeout (too short) |
| Cost (single instance, low traffic) | ~$61/mo (t3.large) | ~$90/mo (similar specs) | ~$75/mo |
| Operations complexity | Medium (SSM management) | Lower | Lowest |
| Proven in our stack | Yes (`sc-cgiar-agent`) | No | No |

**Decision: EC2 + ALB** — mirrors `sc-cgiar-agent` exactly. The pattern is proven, the CloudFormation template is battle-tested, and it handles all three constraints (WebSocket + SQLite + stateful sessions).

### 1.3 What Already Exists in the Repo

| Artifact | Status | Notes |
|----------|--------|-------|
| `Dockerfile` | Exists, but too heavy | 1.7GB image with GUI (VNC, XFCE, browsers). Needs a **lean variant** for production. |
| `docker-compose.yml` | Exists | Good for local dev, not production |
| `.github/workflows/deploy.yml` | Exists, but wrong pattern | Targets the Synapsis Agent infra (Lambda orchestrator, ASG). Needs rewrite. |
| `infra/template.yaml` | Exists, but wrong infra | Synapsis Agent multi-tenant pattern. Needs new template. |
| IAMSetup registration | Missing | `cgiar-innovation-analytics` not in `projects.json` |

### 1.4 Key Differences from `sc-cgiar-agent`

| Aspect | sc-cgiar-agent | cgiar-innovation-analytics |
|--------|---------------|---------------------------|
| Port | 7777 | 7780 |
| Frontend | None (API only) | React + static files served by FastAPI |
| Database | Small SQLite (agent state) | 398MB PRMS SQLite (read-only snapshot) |
| DynamoDB | Yes (pipeline status) | No |
| Litestream | Yes (SQLite replication) | Not needed (PRMS is read-only snapshot) |
| VNC/GUI | No | No (production) |
| Extra tools | PptxGenJS | None |

---

## 2. Proposed Architecture

```
                        ┌──────────────────────────────────┐
                        │          Route53 DNS             │
                        │  innovation-analytics-dev.       │
                        │  synapsis-analytics.com          │
                        └───────────────┬──────────────────┘
                                        │
                        ┌───────────────▼──────────────────┐
                        │     Application Load Balancer     │
                        │  • HTTPS (ACM cert)              │
                        │  • Sticky sessions (WebSocket)   │
                        │  • Idle timeout: 4000s           │
                        └───────────────┬──────────────────┘
                                        │
                        ┌───────────────▼──────────────────┐
                        │     EC2 Instance (t3.large)       │
                        │                                   │
                        │  ┌─────────────────────────────┐ │
                        │  │   Docker Container           │ │
                        │  │   • FastAPI + WebSocket      │ │
                        │  │   • React static files       │ │
                        │  │   • Claude Agent SDK         │ │
                        │  │   • PRMS SQLite (398MB)      │ │
                        │  │   • Port 7780                │ │
                        │  └─────────────────────────────┘ │
                        │                                   │
                        │  EBS Volume (30GB gp3)           │
                        │  CloudWatch Agent                │
                        │  SSM Agent                       │
                        └──────────────────────────────────┘
                                        │
                        ┌───────────────▼──────────────────┐
                        │     SSM Parameter Store           │
                        │  • /cgiar-ia-{stage}/anthropic-key│
                        │  • /cgiar-ia-{stage}/oauth-token │
                        └──────────────────────────────────┘
```

### 2.1 PRMS Database Strategy

The 398MB PRMS SQLite database is a **read-only snapshot** (no writes, no replication needed). Options:

| Strategy | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| **Bundle in Docker image** | Simple, no runtime downloads | +400MB image size, rebuild to update | **Recommended for v1** |
| S3 download at startup | Small image, easy updates | 10-30s cold start delay, needs S3 bucket | Good for future |
| EBS attached volume | Persistent, easy updates via S3 sync | More infra complexity | Overkill for read-only data |

**Recommendation:** Bundle the PRMS database into the Docker image. At 398MB, the total image will be ~800MB-1GB (lean Dockerfile), which is acceptable for EC2 (no Lambda cold-start concerns). When the PRMS snapshot is updated, rebuild and redeploy.

### 2.2 Lean Production Dockerfile

The existing Dockerfile includes VNC, GUI apps, browsers, LibreOffice (~1.7GB). For production, we need a **lean variant** that strips all GUI dependencies:

```dockerfile
# Stage 1: Frontend build
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Application
FROM python:3.12-slim
# ... minimal deps: FastAPI, Claude SDK, SQLite
# ... copy PRMS database
# ... copy frontend static files
# ... port 7780, health check
```

Estimated image size: ~800MB (Python base + deps + 398MB PRMS db)

### 2.3 CI/CD Pipeline

```
Push to develop → Deploy to DEV account (972793825893)
Push to staging → Deploy to TST account (053142643230)  
Push to main   → Deploy to PRD account (207258148366)
```

Pipeline steps (mirroring `sc-cgiar-agent`):
1. OIDC authenticate → assume deploy role
2. Build Docker image → push to ECR
3. Store secrets in SSM Parameter Store
4. Deploy CloudFormation stack (EC2 + ALB + Route53)
5. SSM Send-Command: pull new image, restart container
6. Health check verification

### 2.4 Domain & HTTPS

Following the `sc-cgiar-agent` naming convention:
- DEV: `innovation-analytics-dev.synapsis-analytics.com`
- TST: `innovation-analytics-staging.synapsis-analytics.com`
- PRD: `innovation-analytics.synapsis-analytics.com` (or `cgiar-innovation.synapsis-analytics.com`)

---

## 3. Implementation Steps

### Step 1: IAMSetup Registration
Add to `/Users/smithai/workspace/IAMSetup-work/projects.json`:
```json
{
    "repoName": "cgiar-innovation-analytics",
    "gitHubOrg": "cgiar-ppu",
    "description": "CGIAR Innovation Analytics Platform - conversational portfolio intelligence",
    "environments": ["DEV", "TST", "PRD"],
    "region": "eu-central-1",
    "resourcePrefix": "cgiar-ia"
}
```
Push to master → creates deploy roles in all 3 accounts.

### Step 2: Lean Production Dockerfile
Create `Dockerfile.prod` — stripped of VNC, browsers, GUI. Includes:
- Python 3.12-slim base
- FastAPI + Claude Agent SDK + dependencies
- Frontend static build
- PRMS SQLite database copy
- Non-root user, health check

### Step 3: CloudFormation Template
New `infra/template.yaml` based on `sc-cgiar-agent` but adapted:
- No DynamoDB, no Litestream
- Same EC2 + ALB + Route53 pattern
- Same WebSocket-friendly ALB config (4000s idle, sticky sessions)
- Port 7780 instead of 7777
- `resourcePrefix: cgiar-ia`

### Step 4: GitHub Actions Workflow  
New `.github/workflows/deploy.yml` using OIDC pattern:
- Branch → environment mapping
- ECR build & push with Buildx caching
- SSM secrets management
- CloudFormation deploy
- SSM Run-Command for container update
- Health check verification

### Step 5: Environment Configuration
GitHub repository variables needed:
```
AWS_ROLE_ARN_DEV = arn:aws:iam::972793825893:role/cicd/github-actions-cgiar-innovation-analytics-DEV-deploy
AWS_ROLE_ARN_TST = arn:aws:iam::053142643230:role/cicd/github-actions-cgiar-innovation-analytics-TST-deploy
AWS_ROLE_ARN_PRD = arn:aws:iam::207258148366:role/cicd/github-actions-cgiar-innovation-analytics-PRD-deploy
VPC_ID = (DEV account default VPC)
SUBNET_ID_1 = (public subnet AZ-a)
SUBNET_ID_2 = (public subnet AZ-b, for ALB)
ACM_CERTIFICATE_ARN = (wildcard cert for *.synapsis-analytics.com)
HOSTED_ZONE_ID = (Route53 zone for synapsis-analytics.com)
INSTANCE_TYPE = t3.large
```

GitHub repository secrets:
```
ANTHROPIC_API_KEY = (Claude API key)
```

---

## 4. Cost Estimate (DEV environment)

| Resource | Monthly Cost |
|----------|-------------|
| EC2 t3.large (on-demand, eu-central-1) | ~$61 |
| ALB (low traffic) | ~$16 |
| EBS 30GB gp3 | ~$2.40 |
| CloudWatch Logs (1GB/mo) | ~$0.50 |
| ECR (1GB image) | ~$0.10 |
| Route53 hosted zone | ~$0.50 |
| **Total (DEV)** | **~$81/month** |

For initial testing on `ai-sandbox` or `ai-dev`, we could skip the ALB and use direct HTTP access (like `sc-cgiar-agent` in dev mode), bringing cost to ~$63/month.

---

## 5. Rollout Plan

| Phase | Action | Timeline |
|-------|--------|----------|
| 1 | Review & approve this proposal | Now |
| 2 | Register in IAMSetup + push to create deploy roles | 15 min |
| 3 | Create `Dockerfile.prod` + CloudFormation + GitHub Actions | 1-2 hours |
| 4 | Deploy to DEV environment | 30 min |
| 5 | Verify all 8 capabilities work in AWS | 30 min |
| 6 | Configure HTTPS + custom domain | 15 min |
| 7 | Document operational runbook | 30 min |

---

## 6. Open Questions for Review

1. **Target account for initial deploy:** `ai-dev` (972793825893) or `ai-sandbox` (919959486181)?
2. **Domain preference:** `innovation-analytics-dev.synapsis-analytics.com` or different naming?
3. **Instance size:** `t3.large` (2 vCPU, 8GB RAM) sufficient? The Claude Agent SDK sessions are memory-hungry.
4. **PRMS database updates:** How often is the PRMS snapshot refreshed? Should we build an automated pipeline (S3 → container restart) or is manual rebuild acceptable?
5. **Authentication:** Do we need Cognito user authentication for the WebSocket endpoint, or is it internal-only initially?
6. **Branch strategy:** Should `feature/innovation-platform-foundation` deploy to DEV, or should we merge to `develop` first?

---

## 7. Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `Dockerfile.prod` | CREATE | Lean production image (~800MB vs 1.7GB) |
| `infra/template-ec2.yaml` | CREATE | EC2 + ALB CloudFormation (based on sc-cgiar-agent) |
| `.github/workflows/deploy-ec2.yml` | CREATE | OIDC CI/CD pipeline |
| `entrypoint-prod.sh` | CREATE | Production entrypoint (auth, PRMS check, startup) |
| `.github/workflows/deploy.yml` | ARCHIVE/RENAME | Current workflow targets wrong infra |
| IAMSetup `projects.json` | MODIFY | Add cgiar-innovation-analytics entry |
