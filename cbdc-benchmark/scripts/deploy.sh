#!/usr/bin/env bash
# =============================================================================
# CBDC Benchmark — Master Deploy Script
# Usage: ./deploy.sh [--teardown] [--benchmark-only] [--consensus poa|qbft]
# Run from AWS CloudShell after: git clone <repo> && cd cbdc-benchmark
# =============================================================================
set -euo pipefail

# ─── COLORS ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

log()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] $*${NC}"; }
warn()  { echo -e "${YELLOW}[WARN] $*${NC}"; }
error() { echo -e "${RED}[ERROR] $*${NC}"; exit 1; }
title() { echo -e "\n${BOLD}${BLUE}════════════════════════════════════════${NC}"; \
          echo -e "${BOLD}${CYAN}  $*${NC}"; \
          echo -e "${BOLD}${BLUE}════════════════════════════════════════${NC}\n"; }

# ─── PARSE ARGS ──────────────────────────────────────────────────────────────
TEARDOWN=false
BENCHMARK_ONLY=false
CONSENSUS_FILTER="both"  # both | poa | qbft

while [[ $# -gt 0 ]]; do
  case $1 in
    --teardown)        TEARDOWN=true; shift ;;
    --benchmark-only)  BENCHMARK_ONLY=true; shift ;;
    --consensus)       CONSENSUS_FILTER="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ─── AUTO-DETECT AWS ENVIRONMENT ─────────────────────────────────────────────
title "CBDC Benchmark Framework — Initializing"

export AWS_REGION=$(aws configure get region 2>/dev/null || \
  curl -s --max-time 3 http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || \
  echo "us-east-1")
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
STACK_NAME="cbdc-benchmark"
PROJECT_NAME="cbdc-benchmark"
BUCKET_NAME="${PROJECT_NAME}-${AWS_ACCOUNT_ID}-${AWS_REGION}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log "Region:     $AWS_REGION"
log "Account:    $AWS_ACCOUNT_ID"
log "Bucket:     $BUCKET_NAME"
log "Repo root:  $REPO_ROOT"

# ─── TEARDOWN MODE ───────────────────────────────────────────────────────────
if [ "$TEARDOWN" = "true" ]; then
  title "Tearing Down Infrastructure"
  log "Deleting CloudFormation stack: $STACK_NAME"
  aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$AWS_REGION"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$AWS_REGION"
  log "Stack deleted."
  # Optionally empty and delete bucket
  read -p "Delete S3 bucket and all results? [y/N] " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    aws s3 rm "s3://${BUCKET_NAME}" --recursive
    aws s3 rb "s3://${BUCKET_NAME}"
    log "Bucket deleted."
  fi
  exit 0
fi

# ─── DEPENDENCIES CHECK ───────────────────────────────────────────────────────
title "Checking Dependencies"
for cmd in aws python3 jq; do
  if ! command -v "$cmd" &>/dev/null; then
    error "$cmd is required but not installed"
  fi
  log "✓ $cmd"
done

# Install Python dependencies
log "Installing Python packages..."
pip install -q boto3 web3 pandas openpyxl matplotlib seaborn numpy eth-account requests tqdm 2>/dev/null || true

# ─── DATASET CHECK ────────────────────────────────────────────────────────────
title "Dataset Preparation"
DATASET_PATH=""
# Search common locations
for p in \
  "${REPO_ROOT}/dataset/FinalDataset.xlsx" \
  "${HOME}/FinalDataset.xlsx" \
  "/tmp/FinalDataset.xlsx" \
  "FinalDataset.xlsx"; do
  if [ -f "$p" ]; then
    DATASET_PATH="$p"
    break
  fi
done

if [ -z "$DATASET_PATH" ]; then
  warn "FinalDataset.xlsx not found locally."
  warn "Please upload the file to CloudShell, then re-run:"
  warn "  cp ~/FinalDataset.xlsx ${REPO_ROOT}/dataset/"
  warn "Continuing — you can upload the dataset manually to S3 later."
else
  log "Dataset found: $DATASET_PATH"
fi

# ─── INFRASTRUCTURE PROVISIONING ─────────────────────────────────────────────
if [ "$BENCHMARK_ONLY" = "false" ]; then
  title "Provisioning Infrastructure (CloudFormation)"

  # Check if stack already exists
  STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].StackStatus" \
    --output text 2>/dev/null || echo "DOES_NOT_EXIST")

  if [[ "$STACK_STATUS" == "DOES_NOT_EXIST" || "$STACK_STATUS" == "DELETE_COMPLETE" ]]; then
    log "Creating CloudFormation stack..."
    aws cloudformation create-stack \
      --stack-name "$STACK_NAME" \
      --template-body "file://${REPO_ROOT}/infrastructure/cloudformation.yaml" \
      --capabilities CAPABILITY_NAMED_IAM \
      --region "$AWS_REGION" \
      --parameters \
        ParameterKey=ProjectName,ParameterValue="$PROJECT_NAME" \
        ParameterKey=InstanceType,ParameterValue="t3.medium"
  elif [[ "$STACK_STATUS" == "UPDATE_ROLLBACK_COMPLETE" || "$STACK_STATUS" == "CREATE_COMPLETE" || "$STACK_STATUS" == "UPDATE_COMPLETE" ]]; then
    log "Stack exists (status: $STACK_STATUS). Skipping creation."
  else
    log "Updating existing stack..."
    aws cloudformation update-stack \
      --stack-name "$STACK_NAME" \
      --template-body "file://${REPO_ROOT}/infrastructure/cloudformation.yaml" \
      --capabilities CAPABILITY_NAMED_IAM \
      --region "$AWS_REGION" \
      --parameters \
        ParameterKey=ProjectName,ParameterValue="$PROJECT_NAME" \
        ParameterKey=InstanceType,ParameterValue="t3.medium" || true
  fi

  log "Waiting for stack to be ready (this takes ~5 minutes)..."
  aws cloudformation wait stack-create-complete \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" 2>/dev/null || \
  aws cloudformation wait stack-update-complete \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" 2>/dev/null || true

  log "Stack ready."
fi

# ─── FETCH STACK OUTPUTS ─────────────────────────────────────────────────────
title "Reading Stack Outputs"

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

NODE1_IP=$(get_output "Node1IP")
NODE2_IP=$(get_output "Node2IP")
NODE3_IP=$(get_output "Node3IP")
NODE4_IP=$(get_output "Node4IP")
BENCHMARK_INSTANCE_ID=$(get_output "BenchmarkInstanceId")
BUCKET_NAME=$(get_output "BucketName")

log "Node 1:    $NODE1_IP"
log "Node 2:    $NODE2_IP"
log "Node 3:    $NODE3_IP"
log "Node 4:    $NODE4_IP"
log "Benchmark: $BENCHMARK_INSTANCE_ID"
log "Bucket:    $BUCKET_NAME"

RPC_URL="http://${NODE1_IP}:8545"

# ─── UPLOAD DATASET ───────────────────────────────────────────────────────────
title "Uploading Dataset to S3"
if [ -n "$DATASET_PATH" ]; then
  aws s3 cp "$DATASET_PATH" "s3://${BUCKET_NAME}/dataset/FinalDataset.xlsx"
  log "✓ Dataset uploaded to s3://${BUCKET_NAME}/dataset/FinalDataset.xlsx"
else
  # Check if already in S3
  if aws s3 ls "s3://${BUCKET_NAME}/dataset/FinalDataset.xlsx" &>/dev/null; then
    log "✓ Dataset already in S3"
  else
    warn "Dataset not in S3. Upload FinalDataset.xlsx manually:"
    warn "  aws s3 cp FinalDataset.xlsx s3://${BUCKET_NAME}/dataset/FinalDataset.xlsx"
  fi
fi

# ─── SETUP BESU ON NODES VIA SSM ─────────────────────────────────────────────
title "Setting Up Besu Nodes via SSM"

setup_besu_node() {
  local instance_id="$1"
  local consensus="$2"  # poa or qbft

  log "Configuring $instance_id for $consensus..."

  aws ssm send-command \
    --instance-ids "$instance_id" \
    --document-name "AWS-RunShellScript" \
    --region "$AWS_REGION" \
    --parameters "commands=[
      \"set -e\",
      \"yum install -y docker python3-pip git 2>/dev/null || true\",
      \"systemctl start docker 2>/dev/null || true\",
      \"pip3 install eth-account 2>/dev/null || true\",
      \"mkdir -p /opt/cbdc-benchmark\",
      \"cd /opt/cbdc-benchmark\",
      \"aws s3 cp s3://${BUCKET_NAME}/repo/cbdc-benchmark.tar.gz . 2>/dev/null || true\",
      \"docker pull hyperledger/besu:latest\",
      \"echo 'Node setup complete'\"
    ]" \
    --output text --query "Command.CommandId" 2>/dev/null || \
    warn "SSM command failed for $instance_id (may need SSM agent time)"
}

# Upload repo to S3 for nodes to download
log "Packaging and uploading repo to S3..."
cd "$REPO_ROOT/.."
tar czf /tmp/cbdc-benchmark.tar.gz cbdc-benchmark/ 2>/dev/null || true
aws s3 cp /tmp/cbdc-benchmark.tar.gz "s3://${BUCKET_NAME}/repo/cbdc-benchmark.tar.gz" || true
cd "$REPO_ROOT"

# ─── WAIT FOR INSTANCES ───────────────────────────────────────────────────────
title "Waiting for EC2 Instances to Initialize"
log "Waiting 90 seconds for instances to bootstrap Docker..."
sleep 90

# ─── RUN BENCHMARKS ──────────────────────────────────────────────────────────
RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
log "Run ID: $RUN_ID"

run_benchmark() {
  local consensus="$1"
  local compose_file="$2"
  local chain_id="$3"

  title "Running $consensus Benchmark"
  log "Starting 4-node $consensus network on benchmark instance..."

  # Deploy network on benchmark instance via SSM
  CMD_ID=$(aws ssm send-command \
    --instance-ids "$BENCHMARK_INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --region "$AWS_REGION" \
    --parameters "commands=[
      \"set -e\",
      \"cd /opt/cbdc-benchmark\",
      \"tar xzf cbdc-benchmark.tar.gz 2>/dev/null || true\",
      \"cd cbdc-benchmark\",
      \"export AWS_REGION=${AWS_REGION}\",
      \"export AWS_DEFAULT_REGION=${AWS_REGION}\",

      # Generate node keys + patch genesis
      \"python3 scripts/bootstrap-network.py --consensus ${consensus,,} --node-count 4 --base-dir /opt/besu\",

      # Start network
      \"docker-compose -f docker/${compose_file} down -v 2>/dev/null || true\",
      \"docker-compose -f docker/${compose_file} up -d\",
      \"echo 'Waiting 30s for network to stabilize...'\",
      \"sleep 30\",

      # Run workload
      \"pip3 install -q boto3 web3 pandas openpyxl matplotlib seaborn numpy eth-account requests tqdm\",
      \"python3 benchmark/workload-loader.py \\\\
        --rpc-url http://localhost:8545 \\\\
        --consensus ${consensus} \\\\
        --bucket ${BUCKET_NAME} \\\\
        --dataset-key dataset/FinalDataset.xlsx \\\\
        --target-tps 50 \\\\
        --duration 300 \\\\
        --run-id ${RUN_ID} \\\\
        --region ${AWS_REGION}\",

      \"echo 'Benchmark complete for ${consensus}'\"
    ]" \
    --output text --query "Command.CommandId")

  log "$consensus SSM Command ID: $CMD_ID"
  log "Waiting for $consensus benchmark to complete (~8 minutes)..."

  # Poll for completion
  for i in $(seq 1 60); do
    sleep 10
    STATUS=$(aws ssm get-command-invocation \
      --command-id "$CMD_ID" \
      --instance-id "$BENCHMARK_INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query "Status" --output text 2>/dev/null || echo "Pending")
    log "  Status: $STATUS (${i}0s elapsed)"
    if [[ "$STATUS" == "Success" ]]; then
      log "✓ $consensus benchmark completed successfully"
      break
    elif [[ "$STATUS" == "Failed" || "$STATUS" == "Cancelled" ]]; then
      warn "$consensus benchmark $STATUS. Checking output..."
      aws ssm get-command-invocation \
        --command-id "$CMD_ID" \
        --instance-id "$BENCHMARK_INSTANCE_ID" \
        --region "$AWS_REGION" \
        --query "StandardErrorContent" --output text || true
      break
    fi
  done
}

# Run based on filter
if [[ "$CONSENSUS_FILTER" == "both" || "$CONSENSUS_FILTER" == "poa" ]]; then
  run_benchmark "PoA" "docker-compose.poa.yml" "1337"
fi

if [[ "$CONSENSUS_FILTER" == "both" || "$CONSENSUS_FILTER" == "qbft" ]]; then
  run_benchmark "QBFT" "docker-compose.qbft.yml" "1338"
fi

# ─── GENERATE REPORTS ────────────────────────────────────────────────────────
title "Generating Comparison Reports"
log "Generating charts and reports for run: $RUN_ID"

python3 "${REPO_ROOT}/benchmark/report-generator.py" \
  --bucket "$BUCKET_NAME" \
  --run-id "$RUN_ID" \
  --region "$AWS_REGION"

# ─── RESULTS SUMMARY ─────────────────────────────────────────────────────────
title "🎉 Benchmark Complete!"
echo ""
log "Run ID: $RUN_ID"
log "Results bucket: s3://${BUCKET_NAME}/results/${RUN_ID}/"
echo ""
log "Download results:"
log "  aws s3 sync s3://${BUCKET_NAME}/results/${RUN_ID}/ ./results/${RUN_ID}/"
echo ""
log "CloudWatch Dashboard:"
log "  https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}#dashboards:name=${PROJECT_NAME}-performance"
echo ""
log "To re-run benchmark only:"
log "  ./scripts/run-benchmark.sh --run-id ${RUN_ID}"
echo ""
log "To tear down:"
log "  ./deploy.sh --teardown"
