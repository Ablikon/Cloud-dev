# Cloud-dev

Cloud Application Development — practice work.
AWS account `412004015750`, region `eu-north-1` (Stockholm).

## Practice 1 — account bootstrap
Account created and hardened (root MFA, no root access keys, password policy),
AWS CLI installed and configured, access verified with `sts:GetCallerIdentity`,
and a 10 USD monthly cost budget with two alert thresholds.

- `policies/budget.json` — the monthly COST budget
- `policies/notifications.json` — ACTUAL > 80% and FORECASTED > 100% alerts

## Practice 2 — least-privilege IAM and Secrets Manager
An IAM group, user and role, each carrying only the permissions it needs, and an
application secret in Secrets Manager reachable only by assuming the role.

- `policies/cad-assume-secret-reader.json` — group policy: `sts:AssumeRole` on one
  role ARN, plus own-MFA and own-password self-service
- `policies/cad-read-one-secret.json` — role policy: `GetSecretValue` and
  `DescribeSecret` on one secret ARN
- `policies/cad-secret-reader-trust.json` — trust policy naming `cad-dev-01` as the
  only principal permitted to assume the role

## Practice 5 — a queue, a dead-letter queue and an idempotent consumer
An `OrderPlaced` domain event on a custom EventBridge bus, routed by an event
pattern to an SQS queue, drained by a Lambda consumer that is safe to run twice.
The deduplication key is the business key (`orderId`), not the SQS `messageId`:
a client retry produces a new message for the same order.

- `practice5/handler.py` — the consumer; dedup marker and balance are written in
  one `TransactWriteItems`, so a timeout cannot credit an account twice
- `practice5/queue-attributes.json` — visibility timeout, retention and the
  redrive policy (`maxReceiveCount` 5)
- `practice5/policies/eventbridge-rule-pattern.json` — the routing pattern
- `practice5/policies/queue-access-policy.json` — only this rule may send
- `practice5/policies/consumer-least-privilege.json` — one queue, two tables,
  one log group

## Practice 6 — the same consumer as a container on Fargate
The Practice 5 consumer rebuilt as a long-running service: an HTTP listener for
the load balancer's health check and its own 20-second long-polling loop, since
nothing hands a container a batch.

- `practice6/app/` — `worker.py`, `requirements.txt` and a `Dockerfile` pinned to
  a base-image digest rather than a moving tag
- `practice6/ecr-lifecycle-policy.json` — keep the five newest commit-tagged
  images, expire untagged layers after a day

## Notes
No credentials are stored in this repository. The secret value lives only in
AWS Secrets Manager; access keys live only in `~/.aws/credentials` on the
workstation and are excluded by `.gitignore`.

> `policies/notifications.json` carries a placeholder subscriber address.
> Replace `YOUR_EMAIL@example.com` before applying it.

## SIS 1 — custom VPC, two zones, application behind a load balancer

A three-tier VPC in 10.0.0.0/16: two public /24s for the load balancer and the NAT
Gateway, two private /20s for the application, two private /24s reserved for the
database tier. The application runs in an Auto Scaling group across both private app
subnets, behind an internet-facing Application Load Balancer. Torn down after grading;
the NAT Gateway was the dominant cost at $0.046/hour.

- `sis1/address-plan.txt` — the subnet plan, written before anything was created
- `sis1/userdata.sh` — installs nginx and a systemd unit that regenerates the instance
  identity page from IMDSv2 on every boot
- `sis1/launch-template-data.json` — private subnets, no public IP, IMDSv2 required,
  encrypted gp3 root volume
- `sis1/policies/ec2-instance-trust.json` — trust policy for the Session Manager role

## Practice 3 — private S3 bucket behind CloudFront, and a presigned URL

A static front end in a private bucket, published only through a CloudFront
distribution using origin access control. Block Public Access stays on throughout; the
same object returns 403 when requested straight from S3. A second bucket holds a private
object used to demonstrate a presigned URL working and then expiring.

- `practice3/policies/bucket-policy-oac.json` — allows `s3:GetObject` to CloudFront only
  when `AWS:SourceArn` matches one distribution, and denies everything over plain HTTP
- `practice3/policies/lifecycle.json` — expires noncurrent versions after 30 days keeping
  the newest 3, and aborts incomplete multipart uploads after 7 days
- `practice3/distribution-config.json` — REST origin (not the website endpoint), OAC,
  redirect-to-https, managed CachingOptimized policy
- `practice3/dist/` — the front end: a content-hashed stylesheet and `index.html`

These resources are retained rather than deleted: the week 5 brief states that SIS 2
builds on this bucket and distribution.

## Architecture diagrams

`docs/fig-sis1.png` and `docs/fig-p3.png`.

## Practice 4 — Multi-AZ RDS reached by name, and DynamoDB keyed from access patterns

A PostgreSQL instance in two private subnets across two Availability Zones, through a
DB subnet group, admitting connections only from the application's security group. The
application resolves both the host and the password at runtime, so a forced Multi-AZ
failover — which moved the endpoint from 10.1.16.45 to 10.1.17.253 in thirty seconds —
required no change to it at all. The database was deleted afterwards; the brief is
explicit that Multi-AZ is never in the free allowance.

- `practice4/access-patterns.txt` — written before the key schema, because the keys
  follow from the questions
- `practice4/dynamodb-table.json` — composite key plus one GSI; every access pattern is
  served by Query or GetItem, never by Scan
- `practice4/app-connect.sh` — fetches the credential from Secrets Manager, connects by
  endpoint name with TLS required, and creates a least-privilege database role
- `practice4/policies/read-one-db-secret.json` — GetSecretValue on one ARN, not on `*`

Measured: the same eight orders cost 0.5 RCU through the index and 2.0 RCU through a
Scan, because a FilterExpression is applied after the read.

## SIS 2 — the orders read path, reimplemented as a Lambda function

One part of the project moved to Lambda: the DynamoDB queries that Practice 4 ran by
hand. python3.13 on arm64, invoked through a function URL qualified to an alias, with
`AWS_IAM` auth so an unsigned request is refused.

The release mechanism is the submission. Version 1 was published and the alias `live`
pointed at it; version 2 was published and the alias moved, and the same caller holding
the same URL received the new code — `codeVersion` 1.0.0 became 1.1.0 and a new field
appeared — without being told anything.

The execution role is least-privilege in a way that can be proved rather than claimed:
`dynamodb:Query` on two ARNs and nothing else. A probe deliberately attempting a Scan
was refused with `AccessDeniedException ... not authorized to perform: dynamodb:Scan`.

- `sis2/handler.py` — one function, two related routes; the trade-off is written at the
  top of the file. Query only, structured JSON logs, never the raw event
- `sis2/policies/query-orders-inline.json` — one action, two resources
- `sis2/release.sh` — publish a version, move the alias

Note: the function URL is omitted from this repository on purpose; it is in the report.
