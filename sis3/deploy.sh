#!/usr/bin/env bash
# One command, from a clean checkout, to a running environment.
#
#   ./deploy.sh <env>        e.g. ./deploy.sh dev
#
# It is idempotent: run it twice and the second run is a no-op change set.
set -euo pipefail

ENV_NAME="${1:-}"
[[ -n "$ENV_NAME" ]] || { echo "usage: $0 <env>   (dev | test | prod)"; exit 2; }
[[ "$ENV_NAME" =~ ^[a-z][a-z0-9-]{1,12}$ ]] || { echo "env must match ^[a-z][a-z0-9-]{1,12}$"; exit 2; }

REGION="${AWS_REGION:-eu-north-1}"
ECR_STACK="${ECR_STACK:-cad-sis3-ecr}"
APP_STACK="cad-sis3-${ENV_NAME}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The tag is the commit, always. Never "latest": a moving tag makes it
# impossible to say afterwards which code a task was running.
SHA="$(git -C "$HERE" rev-parse --short=7 HEAD)"
if [[ -n "$(git -C "$HERE" status --porcelain -- "$HERE")" ]]; then
  echo "!! sis3/ has uncommitted changes; the image would not match tag git-${SHA}" >&2
  echo "   commit first, or export ALLOW_DIRTY=1 to build anyway" >&2
  [[ "${ALLOW_DIRTY:-0}" == "1" ]] || exit 1
fi
TAG="git-${SHA}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

echo "==> 1/4  registry stack ${ECR_STACK}"
aws cloudformation deploy \
  --template-file "${HERE}/infra/ecr.yaml" \
  --stack-name "${ECR_STACK}" \
  --region "${REGION}" \
  --no-fail-on-empty-changeset

REPO_URI="$(aws cloudformation describe-stacks --stack-name "${ECR_STACK}" --region "${REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text)"
REPO_NAME="${REPO_URI##*/}"

echo "==> 2/4  image ${REPO_NAME}:${TAG}"
if aws ecr describe-images --repository-name "${REPO_NAME}" --region "${REGION}" \
     --image-ids "imageTag=${TAG}" >/dev/null 2>&1; then
  echo "    already in the registry; tags are immutable, nothing to push"
else
  aws ecr get-login-password --region "${REGION}" \
    | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
  # --provenance=false: buildx otherwise pushes an attestation manifest under the
  # same tag, and an IMMUTABLE repository rejects that second write.
  docker build --platform linux/arm64 --provenance=false \
    -t "${REPO_URI}:${TAG}" "${HERE}/app"
  docker push "${REPO_URI}:${TAG}"
fi

echo "==> 3/4  application stack ${APP_STACK}"
aws cloudformation deploy \
  --template-file "${HERE}/infra/app.yaml" \
  --stack-name "${APP_STACK}" \
  --region "${REGION}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
      "EnvName=${ENV_NAME}" \
      "ImageTag=${TAG}" \
      "EcrStackName=${ECR_STACK}" \
      ${EXTRA_PARAMS:-}

echo "==> 4/4  smoke test"
URL="$(aws cloudformation describe-stacks --stack-name "${APP_STACK}" --region "${REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='HealthUrl'].OutputValue" --output text)"
for attempt in $(seq 1 20); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${URL}" || true)"
  [[ "$code" == "200" ]] && { echo "    ${URL} -> 200"; break; }
  echo "    attempt ${attempt}: ${URL} -> ${code:-no answer}"
  sleep 15
done
[[ "${code:-}" == "200" ]] || { echo "!! service did not become healthy" >&2; exit 1; }

aws cloudformation describe-stacks --stack-name "${APP_STACK}" --region "${REGION}" \
  --query "Stacks[0].Outputs[].{Output:OutputKey,Value:OutputValue}" --output table
