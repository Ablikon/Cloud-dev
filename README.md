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
