#!/usr/bin/env bash
# =============================================================================
# Destroy all CBDC benchmark resources
# Usage: ./scripts/destroy.sh [--keep-data]
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date '+%H:%M:%S')] $*${NC}"; }
warn() { echo -e "${YELLOW}[WARN] $*${NC}"; }

KEEP_DATA=false
[[ "${1:-}" == "--keep-data" ]] && KEEP_DATA=true

export AWS_REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
STACK_NAME="cbdc-benchmark"
BUCKET_NAME="cbdc-benchmark-${AWS_ACCOUNT_ID}-${AWS_REGION}"

log "Destroying CBDC benchmark infrastructure..."
log "Region:  $AWS_REGION"
log "Stack:   $STACK_NAME"
log "Bucket:  $BUCKET_NAME"

# Delete CF stack
log "Deleting CloudFormation stack..."
aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$AWS_REGION" 2>/dev/null || \
  warn "Stack not found or already deleted"

aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$AWS_REGION" 2>/dev/null || true
log "Stack deleted."

if [ "$KEEP_DATA" = "false" ]; then
  log "Emptying and deleting S3 bucket..."
  aws s3 rm "s3://${BUCKET_NAME}" --recursive 2>/dev/null || true
  aws s3 rb "s3://${BUCKET_NAME}" --force 2>/dev/null || true
  log "Bucket deleted."
else
  log "Keeping S3 data (--keep-data flag set)"
  log "Data available at: s3://${BUCKET_NAME}/"
fi

log "✓ All resources destroyed."
