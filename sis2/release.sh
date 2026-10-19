#!/bin/bash
# SIS 2 release: publish an immutable version, then move the alias.
# The caller's URL names the alias, so nothing on the caller's side changes.
set -euo pipefail
FN=cad-sis2-orders

cd "$(dirname "$0")" && rm -f fn.zip && zip -q fn.zip handler.py
aws lambda update-function-code --function-name "$FN" --zip-file fileb://fn.zip
aws lambda wait function-updated-v2 --function-name "$FN"

V=$(aws lambda publish-version --function-name "$FN" \
      --description "${1:-release}" --query Version --output text)
echo "published version $V"

aws lambda update-alias --function-name "$FN" --name live --function-version "$V"
echo "alias live -> $V"
