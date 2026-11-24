#!/usr/bin/env bash
# Delete one environment. The registry stack is deliberately NOT deleted: it is
# shared, and its repository is Retain-protected anyway.
set -euo pipefail
ENV_NAME="${1:?usage: $0 <env>}"
REGION="${AWS_REGION:-eu-north-1}"
STACK="cad-sis3-${ENV_NAME}"
aws cloudformation delete-stack --stack-name "${STACK}" --region "${REGION}"
echo "deleting ${STACK} ..."
aws cloudformation wait stack-delete-complete --stack-name "${STACK}" --region "${REGION}"
echo "${STACK} deleted"
# Log groups created by the stack go with it; check for anything Retain left.
aws logs describe-log-groups --log-group-name-prefix "/ecs/${STACK}" --region "${REGION}" \
  --query 'logGroups[].logGroupName' --output text
