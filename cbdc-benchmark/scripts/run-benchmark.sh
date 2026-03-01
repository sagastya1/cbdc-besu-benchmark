#!/usr/bin/env bash
# =============================================================================
# Run Benchmark Only — reuse existing infrastructure
# Usage: ./scripts/run-benchmark.sh [--run-id <id>] [--consensus poa|qbft|both]
#                                   [--tps 50] [--duration 300]
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'
log()  { echo -e "${GREEN}[$(date '+%H:%M:%S')] $*${NC}"; }
warn() { echo -e "${YELLOW}[WARN] $*${NC}"; }

# ─── ARGS ────────────────────────────────────────────────────────────────────
RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
CONSENSUS="both"
TARGET_TPS=50
DURATION=300

while [[ $# -gt 0 ]]; do
  case $1 in
    --run-id)    RUN_ID="$2"; shift 2 ;;
    --consensus) CONSENSUS="$2"; shift 2 ;;
    --tps)       TARGET_TPS="$2"; shift 2 ;;
    --duration)  DURATION="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

# ─── ENV ─────────────────────────────────────────────────────────────────────
export AWS_REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
STACK_NAME="cbdc-benchmark"
PROJECT_NAME="cbdc-benchmark"

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

BUCKET_NAME=$(get_output "BucketName")
BENCHMARK_INSTANCE_ID=$(get_output "BenchmarkInstanceId")

log "Run ID:     $RUN_ID"
log "Consensus:  $CONSENSUS"
log "Target TPS: $TARGET_TPS"
log "Duration:   ${DURATION}s"
log "Bucket:     $BUCKET_NAME"
log "Instance:   $BENCHMARK_INSTANCE_ID"

# ─── BENCHMARK FUNCTION ───────────────────────────────────────────────────────
run_single() {
  local c="$1"  # PoA or QBFT
  local compose_file
  if [[ "${c,,}" == "poa" ]]; then compose_file="docker-compose.poa.yml"; else compose_file="docker-compose.qbft.yml"; fi

  log "Starting ${c} benchmark (TPS=${TARGET_TPS}, ${DURATION}s)..."

  CMD_ID=$(aws ssm send-command \
    --instance-ids "$BENCHMARK_INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --region "$AWS_REGION" \
    --parameters "commands=[
      \"set -e\",
      \"cd /opt/cbdc-benchmark/cbdc-benchmark\",
      \"export AWS_REGION=${AWS_REGION}\",
      \"python3 scripts/bootstrap-network.py --consensus ${c,,} --node-count 4 --base-dir /opt/besu\",
      \"docker-compose -f docker/${compose_file} down -v 2>/dev/null || true\",
      \"docker-compose -f docker/${compose_file} up -d\",
      \"sleep 30\",
      \"python3 benchmark/workload-loader.py \\\\
        --rpc-url http://localhost:8545 \\\\
        --consensus ${c} \\\\
        --bucket ${BUCKET_NAME} \\\\
        --dataset-key dataset/FinalDataset.xlsx \\\\
        --target-tps ${TARGET_TPS} \\\\
        --duration ${DURATION} \\\\
        --run-id ${RUN_ID} \\\\
        --region ${AWS_REGION}\",
      \"docker-compose -f docker/${compose_file} down -v\"
    ]" \
    --output text --query "Command.CommandId")

  log "$c command: $CMD_ID"

  for i in $(seq 1 80); do
    sleep 10
    STATUS=$(aws ssm get-command-invocation \
      --command-id "$CMD_ID" --instance-id "$BENCHMARK_INSTANCE_ID" \
      --region "$AWS_REGION" --query "Status" --output text 2>/dev/null || echo "Pending")
    [[ "$STATUS" == "Success" ]] && { log "✓ $c done"; break; }
    [[ "$STATUS" == "Failed" || "$STATUS" == "Cancelled" ]] && { warn "$c $STATUS"; break; }
    log "  $c: $STATUS (${i}0s)"
  done
}

[[ "$CONSENSUS" == "both" || "$CONSENSUS" == "poa"  ]] && run_single "PoA"
[[ "$CONSENSUS" == "both" || "$CONSENSUS" == "qbft" ]] && run_single "QBFT"

# Generate reports
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log "Generating reports..."
python3 "${REPO_ROOT}/benchmark/report-generator.py" \
  --bucket "$BUCKET_NAME" \
  --run-id "$RUN_ID" \
  --region "$AWS_REGION"

log ""
log "✓ Done! Results: s3://${BUCKET_NAME}/results/${RUN_ID}/reports/"
log "  aws s3 sync s3://${BUCKET_NAME}/results/${RUN_ID}/ ./results/${RUN_ID}/"
