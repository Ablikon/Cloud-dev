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
