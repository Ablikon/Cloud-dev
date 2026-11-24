# SIS 3 — the asynchronous order pipeline, as code

An `OrderPlaced` domain event on an EventBridge bus is routed by an event pattern
to an SQS queue with a dead-letter queue, and drained by an idempotent consumer
that runs as an ECS Fargate service in private subnets behind an Application Load
Balancer. Everything in this directory is the system: there is nothing to click.

## Deploy

```
./deploy.sh dev
```

That is the whole command. It deploys the shared registry stack if it is
missing, builds and pushes the image tagged with the current commit, deploys the
application stack for the named environment, and does not return success until
the load balancer answers `200` on `/healthz`.

Deploy a second, independent copy by naming a different environment:

```
./deploy.sh test
```

Nothing is shared between the two except the registry. Every resource name is
derived from `EnvName`, so `dev` and `test` coexist in one account and region.

Remove one:

```
./teardown.sh test
```

## What is where

| Path | What it is |
| --- | --- |
| `infra/ecr.yaml` | Shared registry: immutable tags, lifecycle policy, scan on push. Deployed once; the repository is `Retain`. |
| `infra/app.yaml` | One environment: network, messaging, data, container service, alarms. |
| `app/` | The consumer image: `worker.py`, `requirements.txt`, `Dockerfile`. |
| `deploy.sh` | The one command above. |
| `teardown.sh` | Deletes one environment's stack. |
| `publish_event.py` | Publishes an `OrderPlaced` fact, for testing. |

## Parameters

| Parameter | Default | Why it exists |
| --- | --- | --- |
| `EnvName` | *(required)* | Prefixes every resource name. This is what makes a second copy possible. |
| `ImageTag` | *(required)* | Must match `git-<sha>`. The pattern rejects `latest` on purpose: a moving tag makes it impossible to say which code a task is running. |
| `EcrStackName` | `cad-sis3-ecr` | Registry stack whose outputs are imported. |
| `DesiredCount` | `2` | Two tasks, one per availability zone. |
| `LogRetentionDays` | `14` | Allowed values only; "never expire" is not one of them. |
| `MaxReceiveCount` | `5` | Receives before a message is parked in the DLQ. Floor of 3, because 1 sends a message to the DLQ on its first transient error. |
| `VpcCidr` | `10.20.0.0/16` | Subnets are derived from it, so moving the range moves them together. |
| `PollThreads` | `2` | Long-polling threads per task. |

**No secrets are stored in these templates.** The application needs none. If it
did, the value would be a Secrets Manager ARN passed as a parameter and resolved
by the container at run time through its task role — never a literal in the
template, and never a plaintext `Environment` entry, which anyone with
`ecs:DescribeTaskDefinition` can read.

## Testing an environment

```
python3 publish_event.py dev o-1042 acct-1 129.50 KZ   # accepted and processed
python3 publish_event.py dev o-1042 acct-1 129.50 KZ   # same order: ignored
python3 publish_event.py dev o-1043 acct-1  50.00 KZ   # below 100: filtered out
```

The deduplication key is the **business key** (`orderId`), not the SQS
`messageId`. A client retry produces a brand-new message for the same order, so
`messageId` would deduplicate nothing. The marker and the balance change are
written in one `TransactWriteItems`: either both or neither, so a timeout between
them cannot credit an account twice.

## Design notes

- **Tasks run in private subnets.** Public subnets with public IPs are cheaper by
  the cost of a NAT gateway and are allowed as a lab shortcut for Practice 6,
  but an application tier reachable from the internet is not the thing to submit
  here.
- **One NAT gateway, not one per availability zone.** A second costs about $32 a
  month and buys AZ-independent egress; the saving wins for a course environment
  and the trade-off is written down rather than discovered in an invoice.
- **An S3 gateway endpoint** carries image-layer traffic, which is free, instead
  of sending it through the NAT gateway at $0.045/GB.
- **Two IAM roles, not one.** The execution role is the ECS agent: pull the
  image, open the log stream. The task role is the application: one queue, two
  tables. They are different principals and share nothing.
- **ARM64 tasks** — about 20% cheaper per vCPU-hour, and the image is built
  natively on an Apple Silicon workstation rather than emulated.
- **The deployment circuit breaker rolls back.** Without it a broken image
  retries until the deployment times out and the stack sits in
  `UPDATE_IN_PROGRESS` for an hour.

## Cost

A running environment is roughly $0.09 per hour: NAT gateway $0.045, load
balancer $0.0225, two ARM Fargate tasks about $0.016, the rest negligible. Left
running, that is about $66 a month per environment. `./teardown.sh <env>` removes
it.
