# Rivet AI — Production-Style AWS Infrastructure for AI Applications

An asynchronous AI application built with AWS, Terraform, FastAPI, Next.js, and Amazon ECS Fargate.

Rivet AI is a cloud-native AI application that allows users to interact with an AI-powered chat interface. It demonstrates how to design, deploy, automate, secure, and monitor an asynchronous application using AWS-managed infrastructure.

The project focuses on more than getting an AI chatbot working. It demonstrates practical cloud engineering principles, including asynchronous processing, infrastructure as code, high availability, automated deployments, observability, fault recovery, performance testing, and cost management.

The project is developed incrementally across three major versions before reaching its final production-oriented release.

---

## Table of Contents

1. Project Overview
2. System Architecture
3. Networking and Availability Architecture
4. Architecture Decisions
5. Infrastructure Components
6. Performance, Availability and Recovery Targets
7. Three Major Development Versions
8. Complete Project Folder Structure
9. Testing Strategy
10. Cost Management
11. Project Deliverables
12. Development Philosophy
13. Project Status

---

## 1\. Project Overview

Rivet AI allows users to submit messages through a web-based chat interface and receive AI-generated responses.

Instead of keeping an HTTP request open while the AI provider generates a response, the backend accepts the request, creates a background job, and publishes it to a managed message queue.

A separate worker processes the job, communicates with the AI provider, and makes the generated response available to the application.

### Core Capabilities

- AI-powered conversational interface.
- Asynchronous AI response generation.
- Independent API and worker services.
- Managed message processing with Amazon SQS.
- PostgreSQL for application and job metadata.
- Temporary browser-based conversations.
- Secure AWS infrastructure managed through Terraform.
- Containerized application deployment using ECS Fargate.
- Automated CI/CD through GitHub Actions.
- Multi-AZ infrastructure and database recovery.
- Application and infrastructure monitoring.
- Performance, availability, and cost validation.

### Technology Stack

| Category | Technology |
| --- | --- |
| Frontend | Next.js 14, TypeScript |
| Backend | Python, FastAPI |
| AI Provider | OpenAI API |
| Background Processing | Amazon SQS |
| Failed Job Handling | SQS Dead-Letter Queue |
| Database | Amazon RDS PostgreSQL 16 |
| Database Migrations | SQLAlchemy, Alembic |
| Object Storage | Amazon S3 |
| Compute | Amazon ECS Fargate |
| Container Registry | Amazon ECR |
| Infrastructure as Code | Terraform |
| Networking | Amazon VPC, Subnets, Security Groups |
| Load Balancing | Application Load Balancer |
| CDN | Amazon CloudFront |
| Edge Security | AWS WAF |
| DNS and Certificates | Route 53, ACM |
| Secrets | AWS Secrets Manager |
| CI/CD | GitHub Actions |
| AWS Authentication | GitHub Actions OIDC |
| Infrastructure Monitoring | Amazon CloudWatch |
| Alerting | SNS, Lambda, Slack |
| Application Tracing | OpenTelemetry |
| Observability Platform | Grafana Cloud |
| Administrative Access | Cloudflare Zero Trust / Tunnel |
| Testing | Pytest, Playwright, Locust or k6 |

**Architecture Note:** Amazon SQS replaces Redis as the initial messaging infrastructure. Celery is not part of the initial implementation. The project uses a lightweight SQS worker so messaging and processing remain separate without introducing another broker or task-processing framework.

---

## 2\. System Architecture

### High-Level Architecture

text

```text
                         END USERS
                             |
                             v
                     NEXT.JS FRONTEND
                             |
                             v
                    ROUTE 53 / CLOUDFRONT
                             |
                             v
                         AWS WAF
                             |
                             v
                    APPLICATION LOAD BALANCER
                             |
                             v
                  ECS FARGATE APPLICATION CLUSTER
                             |
                       FASTAPI SERVICE
                             |
                  +----------+----------+
                  |                     |
                  v                     v
             RDS POSTGRESQL          AMAZON SQS
             Job metadata            Main Queue
                  |                     |
                  |                     v
                  |               SQS WORKER
                  |               ECS FARGATE
                  |                     |
                  |                     v
                  |                 OPENAI API
                  |                     |
                  |                     v
                  |                GENERATED RESULT
                  |                     |
                  |                     v
                  +----------------> AMAZON S3
                                        |
                                        v
                                   CLOUDFRONT
                                        |
                                        v
                                  USER RESPONSE
```

### Request Lifecycle

1. A user opens the Rivet AI web application.
2. The user submits a message.
3. Next.js sends the request to the FastAPI backend.
4. FastAPI validates the request.
5. The backend creates a generation record in PostgreSQL.
6. A transactional outbox mechanism ensures that the job is reliably published to SQS.
7. The API returns a generation ID without waiting for AI generation to finish.
8. An ECS worker receives the message from SQS.
9. The worker retrieves the job and calls the OpenAI API.
10. The generated response is stored and the job status is updated.
11. The frontend retrieves the generation status and result.
12. The user sees the completed AI response.

### Important Architectural Distinction

The API and worker are separate ECS services.

| Component | Responsibility |
| --- | --- |
| FastAPI | Handles HTTP requests |
| Worker | Handles background processing |
| SQS | Distributes background jobs |
| PostgreSQL | Maintains authoritative job state |
| S3 | Stores generated assets when object storage is needed |

This separation allows the API and worker to scale independently.

---

## 3\. Networking and Availability Architecture

Rivet AI uses a multi-AZ AWS network design.

### VPC Structure

The production network is organized into separate subnet tiers across two Availability Zones.

| Subnet Tier | AZ-A | AZ-B | Purpose |
| --- | --- | --- | --- |
| Public | Public subnet A | Public subnet B | Internet-facing load balancer and networking |
| Application | App subnet A | App subnet B | FastAPI and worker tasks |
| Data | Data subnet A | Data subnet B | RDS and private data services |
| Operations | Ops subnet A | Ops subnet B | Private administrative and observability services |

The initial development environment may use a smaller configuration to control costs.

### ECS Application Deployment

One application ECS cluster contains two independent services:

| ECS Service | Purpose | Initial Production Target |
| --- | --- | --- |
| FastAPI | Accepts and validates requests | 2 tasks |
| SQS Worker | Processes background jobs | 2 tasks |

Both services can run in private subnets across two Availability Zones.

ECS maintains the desired number of tasks and replaces failed tasks when the service scheduler detects that the desired count is no longer satisfied.

Availability Zone rebalancing can help correct uneven task distribution.

### Database Replication and Recovery

Amazon RDS PostgreSQL is configured with Multi-AZ deployment for production.

The architecture uses:

- A primary database instance.
- A standby instance in another Availability Zone.
- Managed synchronous replication and automatic failover.
- Automated backups.
- Point-in-time recovery.
- Private database subnets.
- Encryption at rest and in transit.

The standby is primarily for availability and failover, not application read scaling.

Development environments can use Single-AZ RDS to reduce costs.

### Operations ECS Cluster

A separate operations cluster can host independently managed internal services.

| Service | Purpose |
| --- | --- |
| Cloudflare Tunnel | Secure private administrative access |
| Flagsmith | Feature flag management |
| OpenTelemetry Collector | Collects application telemetry |
| Jaeger | Distributed trace inspection, if self-hosted |

Flower is not required because the initial architecture does not use Celery.

For production high availability, critical operations services should have tasks distributed across two AZs where appropriate. Cloudflare Tunnel can run multiple connector replicas using one tunnel identity.

Avoid running two replicas of every operations tool automatically. Some tools have additional state, licensing, or database requirements. Their availability and scaling design should be decided individually.

---

## 4\. Architecture Decisions

### ADR-001: Amazon SQS Instead of Redis

**Decision:** Use Amazon SQS as the initial message broker.

**Reasons:**

- Managed infrastructure.
- No Redis cluster to provision.
- Native CloudWatch integration.
- Built-in dead-letter queue support.
- Long polling.
- Managed durability and scalability.
- Reduced infrastructure maintenance.

Redis remains a possible alternative for future architectural experimentation, but it is not part of the initial design.

### ADR-002: Lightweight SQS Worker Instead of Celery

**Decision:** Use a dedicated Python worker that consumes SQS messages.

**Reasons:**

- SQS already provides message delivery and retry-related mechanisms.
- Avoid introducing a separate broker integration.
- Reduce infrastructure and application complexity.
- Maintain independent worker concurrency and scaling.

The trade-off is that some functionality Celery provides, such as task routing and Flower-based task monitoring, must be implemented or handled through other mechanisms.

### ADR-003: ECS Fargate Instead of EC2

**Decision:** Run application containers using ECS Fargate.

**Reasons:**

- No EC2 instance management.
- Independent application and worker services.
- Container-level resource configuration.
- Health-based task replacement.
- Integration with ECR, CloudWatch, and IAM.
- Easier horizontal scaling.

### ADR-004: PostgreSQL with Multi-AZ

**Decision:** Use Amazon RDS PostgreSQL.

**Reasons:**

- Relational storage for generation metadata.
- Transactional job creation.
- Reliable state transitions.
- Automated backups.
- Multi-AZ availability.
- Familiar SQL ecosystem.

PostgreSQL is the authoritative record of job status. SQS is not used as the application's database.

### ADR-005: Temporary Conversations

**Decision:** Do not maintain persistent customer chat history.

Conversations exist only within the browser session.

Refreshing or reopening the page starts a new conversation.

Generation records may still be retained for operational tracking and troubleshooting, subject to a defined retention policy. They should not contain unnecessary conversation history.

### ADR-006: GitHub Actions OIDC

**Decision:** Use OIDC federation for GitHub Actions AWS authentication.

No permanent AWS access keys are stored in GitHub Actions.

Separate IAM roles are used for:

- Terraform planning.
- Terraform infrastructure deployment.
- Application image deployment.

### ADR-007: Separate Application and Operations Clusters

**Decision:** Use two logical ECS clusters.

- Application cluster.
- Operations cluster.

This provides organizational separation between customer-facing workloads and internal infrastructure services.

The clusters can share the VPC while maintaining separate IAM permissions, security groups, and deployment configurations.

### ADR-008: CloudWatch as the Primary Infrastructure Monitoring System

**Decision:** Use CloudWatch for AWS infrastructure metrics, alarms, and logs.

Infrastructure alerting follows:

text

```text
CloudWatch
    |
    v
SNS Topic
    |
    v
Lambda
    |
    v
Slack
```

OpenTelemetry and Grafana Cloud provide additional application-level observability.

---

## 5\. Infrastructure Components

| Component | Responsibility |
| --- | --- |
| Route 53 | DNS management |
| CloudFront | CDN and edge delivery |
| AWS WAF | Web application protection |
| ALB | HTTPS routing to FastAPI |
| VPC | Network isolation |
| Public Subnets | Internet-facing entry points |
| Private Application Subnets | ECS application workloads |
| Private Data Subnets | Database workloads |
| Operations Subnets | Internal management services |
| ECS Application Cluster | Runs API and worker services |
| ECS Operations Cluster | Runs internal operational services |
| ECR | Stores container images |
| RDS PostgreSQL | Stores application and generation metadata |
| SQS | Background job messaging |
| SQS DLQ | Stores repeatedly failing messages |
| S3 | Stores generated assets |
| Secrets Manager | Stores sensitive configuration |
| IAM | Controls service permissions |
| CloudWatch | Logs, metrics, and alarms |
| SNS | Alert distribution |
| Lambda | Processes infrastructure alerts |
| Cloudflare Tunnel | Private administrative access |
| OpenTelemetry | Application instrumentation |
| Grafana Cloud | Application dashboards and telemetry |

---

## 6\. Performance, Availability and Recovery Targets

These are engineering objectives to validate, not achieved results.

| Metric | Target |
| --- | --- |
| Average Traffic | 0.01–0.05 requests/second |
| Daily Generation Volume | 1,000 generations |
| Monthly Generation Volume | 30,000 generations |
| Burst Throughput | 8 requests/second |
| Burst Duration | 60 seconds |
| Burst Request Volume | 480 requests |
| API Acknowledgement Latency | p95 below 500 ms |
| AI Generation Latency | Measured separately |
| Monthly Availability | 99.5% |
| Recovery Time Objective | 60 minutes |
| Database Recovery Point Objective | 15 minutes |
| AWS Infrastructure Budget | Maximum $300/month |
| AI Provider Charges | Tracked separately |

The API acknowledgement target measures how quickly the backend accepts a valid request. It does not measure how long OpenAI takes to generate a complete response.

The application must also implement overload protection, bounded worker concurrency, and provider rate-limit handling.

---

## 7\. Three Major Development Versions

Rivet AI will not be built all at once.

The project is divided into three major versions, each producing a working and demonstrable system.

### Version 1 — Core Application

**Status:** First working release

**Objective:** Build a functioning AI application before introducing complex AWS infrastructure.

#### Features

- Next.js chat interface.
- FastAPI backend.
- OpenAI API integration.
- PostgreSQL database.
- Generation request and status endpoints.
- SQS background queue.
- Python SQS worker.
- SQS dead-letter queue.
- S3 generated asset storage.
- Local Docker development.
- Automated unit and integration tests.

#### Implementation Phases

1. Create repository structure.
2. Build the FastAPI application.
3. Implement request validation.
4. Design the PostgreSQL schema.
5. Add Alembic migrations.
6. Implement SQS publishing.
7. Implement the worker.
8. Integrate OpenAI.
9. Store generated results.
10. Connect the frontend.
11. Implement status polling.
12. Test the complete workflow.

#### Version 1 Architecture

text

```text
Next.js
   |
   v
FastAPI
   |
   +------> PostgreSQL
   |
   v
Amazon SQS
   |
   v
Python Worker
   |
   v
OpenAI API
   |
   v
S3
```

#### Completion Criteria

A user can submit a message, the backend creates a job, a worker processes it, and the frontend displays the generated response.

Everything must work locally before proceeding.

### Version 2 — AWS Infrastructure and Cloud Deployment

**Status:** Cloud engineering release

**Objective:** Move the working application to AWS using Terraform and ECS Fargate.

#### Features

- Terraform remote state.
- AWS VPC.
- Multi-AZ subnet architecture.
- Security groups.
- IAM roles.
- Amazon ECR.
- ECS Fargate.
- Separate API and worker services.
- Amazon RDS PostgreSQL.
- Production Multi-AZ database configuration.
- Amazon SQS and DLQ.
- S3.
- Secrets Manager.
- Application Load Balancer.
- Route 53 and ACM.
- CloudFront and WAF.

#### Implementation Phases

1. Bootstrap Terraform remote state.
2. Build VPC and subnet modules.
3. Configure networking and security.
4. Provision PostgreSQL.
5. Provision SQS and DLQ.
6. Provision S3.
7. Create ECR repositories.
8. Create the application ECS cluster.
9. Deploy FastAPI.
10. Deploy the worker.
11. Configure the ALB.
12. Connect the frontend to the AWS API.
13. Validate database failover and application connectivity.

#### Version 2 Architecture

text

```text
                 INTERNET
                    |
                    v
              CLOUDFRONT + WAF
                    |
                    v
                   ALB
                    |
                    v
              APPLICATION VPC
                    |
          +---------+---------+
          |                   |
          v                   v
       AZ-A                  AZ-B
          |                   |
       API Task            API Task
       Worker              Worker
          |                   |
          +---------+---------+
                    |
          +---------+---------+
          |                   |
          v                   v
       SQS                 RDS
       Main                Primary
       Queue               |
          |                | Replication
          v                v
       Worker             Standby
                    Different AZ
```

#### Completion Criteria

The application is running on AWS, infrastructure is reproducible through Terraform, and both API and worker services operate independently.

### Version 3 — Production Engineering and Reliability

**Status:** Production-readiness release

**Objective:** Improve security, observability, availability, automated deployments, and operational recovery.

#### Features

- GitHub Actions CI/CD.
- GitHub OIDC.
- Immutable Docker image tags.
- Automated Terraform plan/apply.
- Deployment rollback.
- ECS autoscaling.
- Multi-AZ deployment validation.
- CloudWatch dashboards.
- CloudWatch alarms.
- SNS and Lambda alerting.
- Slack notifications.
- OpenTelemetry instrumentation.
- Grafana Cloud dashboards.
- Cloudflare Zero Trust.
- Administrative operations cluster.
- Automated database backups.
- Load testing.
- Failure testing.
- Security scanning.
- AWS Budgets.

#### Implementation Phases

1. Configure GitHub Actions.
2. Configure OIDC federation.
3. Create project-scoped IAM roles.
4. Automate image builds and deployments.
5. Implement immutable image tagging.
6. Implement rollback.
7. Configure ECS autoscaling.
8. Implement application instrumentation.
9. Configure CloudWatch dashboards and alarms.
10. Configure SNS-to-Slack notifications.
11. Deploy the operations cluster.
12. Configure Cloudflare Tunnel.
13. Add Grafana Cloud.
14. Implement load testing.
15. Test worker and queue failures.
16. Validate database recovery.
17. Review IAM and network security.
18. Validate infrastructure costs.

#### Version 3 Architecture

text

```text
                   GITHUB ACTIONS
                         |
                         v
                    AWS OIDC
                         |
              +----------+----------+
              |                     |
              v                     v
        TERRAFORM PIPELINE     DEPLOY PIPELINE
              |                     |
              v                     v
         AWS INFRASTRUCTURE        ECR
                                    |
                                    v
                                ECS FARGATE
                                    |
                  +-----------------+----------------+
                  |                                  |
                  v                                  v
             APPLICATION CLUSTER                OPS CLUSTER
                  |                                  |
              FastAPI                            Cloudflare
              Worker                             OTel Collector
                                                 Flagsmith
                                                 Jaeger (optional)
                  |
                  v
             PostgreSQL / SQS / S3

                  OBSERVABILITY
                       |
              +--------+--------+
              |                 |
              v                 v
          CloudWatch         OpenTelemetry
              |                 |
              v                 v
             SNS             Grafana Cloud
              |
              v
            Lambda
              |
              v
            Slack
```

#### Completion Criteria

The project has automated deployments, monitoring, operational runbooks, load-test evidence, recovery validation, and documented infrastructure costs.

---

## 8\. Complete Project Folder Structure

The following is the intended final repository structure. It is a target structure, not a requirement to create every file during Version 1.

text

```text
rivet-ai/
│
├── apps/
│   │
│   ├── api/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── dependencies.py
│   │   │   │
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── v1/
│   │   │   │       ├── chat.py
│   │   │   │       ├── generations.py
│   │   │   │       └── health.py
│   │   │   │
│   │   │   ├── schemas/
│   │   │   │   ├── chat.py
│   │   │   │   ├── generation.py
│   │   │   │   └── errors.py
│   │   │   │
│   │   │   ├── services/
│   │   │   │   ├── ai_service.py
│   │   │   │   └── generation_service.py
│   │   │   │
│   │   │   ├── repositories/
│   │   │   │   └── generation_repository.py
│   │   │   │
│   │   │   ├── queue/
│   │   │   │   └── publisher.py
│   │   │   │
│   │   │   └── security/
│   │   │       └── validation.py
│   │   │
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   ├── integration/
│   │   │   └── contract/
│   │   │
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   │
│   ├── worker/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── consumer.py
│   │   │   ├── processor.py
│   │   │   │
│   │   │   ├── services/
│   │   │   │   ├── ai_service.py
│   │   │   │   └── asset_service.py
│   │   │   │
│   │   │   ├── repositories/
│   │   │   │   └── generation_repository.py
│   │   │   │
│   │   │   └── resilience/
│   │   │       ├── retry_policy.py
│   │   │       └── idempotency.py
│   │   │
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   ├── integration/
│   │   │   └── failure/
│   │   │
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   │
│   └── web/
│       ├── app/
│       │   ├── page.tsx
│       │   ├── layout.tsx
│       │   └── globals.css
│       │
│       ├── components/
│       │   ├── ChatWindow.tsx
│       │   ├── ChatInput.tsx
│       │   ├── MessageBubble.tsx
│       │   └── LoadingIndicator.tsx
│       │
│       ├── lib/
│       │   └── api.ts
│       │
│       ├── tests/
│       ├── Dockerfile
│       └── package.json
│
├── database/
│   ├── migrations/
│   ├── models/
│   ├── alembic.ini
│   ├── env.py
│   └── README.md
│
├── infra/
│   │
│   ├── bootstrap/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   │
│   ├── modules/
│   │   ├── networking/
│   │   ├── security/
│   │   ├── iam/
│   │   ├── ecr/
│   │   ├── ecs/
│   │   ├── database/
│   │   ├── sqs/
│   │   ├── storage/
│   │   ├── edge/
│   │   ├── secrets/
│   │   ├── observability/
│   │   ├── operations/
│   │   └── cloudflare/
│   │
│   └── environments/
│       ├── dev/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   ├── outputs.tf
│       │   └── terraform.tfvars.example
│       │
│       └── prod/
│           ├── main.tf
│           ├── variables.tf
│           ├── outputs.tf
│           └── terraform.tfvars.example
│
├── tests/
│   ├── e2e/
│   ├── load/
│   ├── resilience/
│   ├── security/
│   └── smoke/
│
├── scripts/
│   ├── local-dev.sh
│   ├── run-migrations.sh
│   ├── smoke-test.sh
│   └── cost-check.sh
│
├── .github/
│   └── workflows/
│       ├── pull-request.yml
│       ├── infrastructure.yml
│       ├── build-deploy.yml
│       └── rollback.yml
│
├── docs/
│   │
│   ├── architecture/
│   │   ├── system-design.md
│   │   ├── infrastructure.md
│   │   ├── request-lifecycle.md
│   │   └── diagrams/
│   │
│   ├── adr/
│   │   ├── 001-async-processing.md
│   │   ├── 002-sqs-over-redis.md
│   │   ├── 003-fargate-over-ec2.md
│   │   ├── 004-multi-az-database.md
│   │   └── 005-oidc-deployment.md
│   │
│   ├── runbooks/
│   │   ├── api-outage.md
│   │   ├── queue-backlog.md
│   │   ├── dlq-recovery.md
│   │   ├── database-recovery.md
│   │   └── deployment-rollback.md
│   │
│   ├── security/
│   ├── testing/
│   ├── cost/
│   └── disaster-recovery/
│
├── .env.example
├── .dockerignore
├── .gitignore
├── .pre-commit-config.yaml
├── docker-compose.yml
├── Makefile
├── README.md
└── LICENSE
```

### Folder Organization Principles

| Directory | Responsibility |
| --- | --- |
| apps/api | HTTP API and application business logic |
| apps/worker | Asynchronous job processing |
| apps/web | Frontend chat interface |
| database | Database models and migrations |
| infra | All AWS infrastructure managed through Terraform |
| tests | Application, infrastructure, and performance testing |
| scripts | Repeatable development and operational commands |
| .github | Automated CI/CD |
| docs | Architectural decisions, diagrams, and operational documentation |

---

## 9\. Testing Strategy

Testing is performed throughout the project.

| Test Category | What It Validates |
| --- | --- |
| Unit Testing | Individual functions and services |
| API Testing | Request validation and HTTP responses |
| Integration Testing | PostgreSQL, SQS, and S3 interactions |
| Contract Testing | API request and response structure |
| End-to-End Testing | Complete user generation workflow |
| Load Testing | Throughput and latency |
| Resilience Testing | Recovery from service and dependency failures |
| Security Testing | IAM, secrets, access, and container security |
| Smoke Testing | Deployment health |

### Required Performance Tests

- Normal traffic simulation.
- 8 requests/second for 60 seconds.
- 480 requests during the burst.
- API p95 acknowledgement latency below 500 ms.
- Queue backlog monitoring.
- Worker processing time measurement.
- AI provider latency measurement.

### Required Recovery Tests

- API task failure.
- Worker task failure.
- Duplicate SQS delivery.
- Queue backlog.
- DLQ message handling.
- Database failover.
- Database restoration.
- ECS deployment rollback.

Results must be recorded rather than assumed.

---

## 10\. Cost Management

The initial AWS infrastructure budget is $300 per month, excluding OpenAI API charges.

Cost monitoring covers:

- ECS Fargate.
- RDS PostgreSQL.
- NAT Gateway or alternative outbound networking.
- Application Load Balancer.
- SQS.
- S3.
- CloudFront.
- CloudWatch.
- WAF.
- Data transfer.
- Operations workloads.

Development and production environments should have different capacity configurations.

A production Multi-AZ database and multiple continuously running Fargate tasks may consume a significant portion of the budget.

Cost estimates should be performed before provisioning, with AWS Budgets and actual billing used for validation.

The $300 target is a constraint to investigate, not a guaranteed outcome.

---

## 11\. Project Deliverables

At completion, Rivet AI should demonstrate:

- A working AI application.
- A documented asynchronous processing architecture.
- Reproducible AWS infrastructure.
- Multi-AZ networking and database deployment.
- Containerized API and worker services.
- Automated CI/CD.
- Secure AWS authentication through OIDC.
- Application and infrastructure observability.
- Load-test evidence.
- Failure and recovery test evidence.
- Documented security controls.
- Infrastructure cost analysis.
- Operational runbooks.
- Architecture decision records.

---

## 12\. Development Philosophy

Rivet AI is being developed incrementally.

The goal is not to deploy every AWS service immediately. The goal is to understand the problem each service solves and introduce it when the application actually needs it.

Each major version must leave behind a working, testable result.

| Version | Focus |
| --- | --- |
| Version 1 | Build the application |
| Version 2 | Deploy the application to AWS |
| Version 3 | Make the application production-oriented through automation, observability, security, and reliability engineering |

The final result should demonstrate the ability to design, build, deploy, test, monitor, and recover a real cloud-native AI application.

---

## 13\. Project Status

**Overall Status:** In Development

| Version | Objective | Status |
| --- | --- | --- |
| Version 1 | Core AI application | Planned |
| Version 2 | AWS infrastructure and deployment | Planned |
| Version 3 | Production engineering and reliability | Planned |
