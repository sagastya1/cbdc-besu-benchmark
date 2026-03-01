#!/bin/bash
# =============================================================
# setup_network.sh — Download Besu and spin up PoA / QBFT node
# =============================================================
set -e

BESU_VERSION="24.1.2"
BESU_DIR="/opt/besu"
NETWORK=$1  # "poa" or "qbft"
DATA_DIR="/tmp/besu-${NETWORK}"

echo "==> Setting up Besu ${BESU_VERSION} for consensus: ${NETWORK}"

# ---- Install Java 21 (Besu requirement) ----------------------
if ! java -version 2>&1 | grep -q "21"; then
  echo "Installing Java 21..."
  apt-get install -y openjdk-21-jre-headless -qq > /dev/null 2>&1
fi

# ---- Download Besu if needed ----------------------------------
if [ ! -f "${BESU_DIR}/bin/besu" ]; then
  echo "Downloading Besu ${BESU_VERSION}..."
  mkdir -p ${BESU_DIR}
  wget -q "https://hyperledger.jfrog.io/artifactory/besu-binaries/besu/${BESU_VERSION}/besu-${BESU_VERSION}.tar.gz" \
       -O /tmp/besu.tar.gz
  tar -xzf /tmp/besu.tar.gz -C ${BESU_DIR} --strip-components=1
  echo "Besu installed at ${BESU_DIR}"
fi

export PATH="${BESU_DIR}/bin:$PATH"

# ---- Clean old data -------------------------------------------
rm -rf ${DATA_DIR}
mkdir -p ${DATA_DIR}

# ---- Select genesis -------------------------------------------
if [ "${NETWORK}" = "poa" ]; then
  GENESIS_FILE="$(dirname $0)/../config/genesis-poa.json"
  RPC_PORT=8545
  P2P_PORT=30303
  CONSENSUS_ARGS="--rpc-http-api=ETH,NET,WEB3,CLIQUE,ADMIN,TXPOOL"
elif [ "${NETWORK}" = "qbft" ]; then
  GENESIS_FILE="$(dirname $0)/../config/genesis-qbft.json"
  RPC_PORT=8546
  P2P_PORT=30304
  CONSENSUS_ARGS="--rpc-http-api=ETH,NET,WEB3,QBFT,ADMIN,TXPOOL"
else
  echo "Usage: $0 [poa|qbft]"
  exit 1
fi

echo "==> Starting Besu ${NETWORK} node on port ${RPC_PORT}..."

nohup ${BESU_DIR}/bin/besu \
  --genesis-file="${GENESIS_FILE}" \
  --data-path="${DATA_DIR}" \
  --rpc-http-enabled=true \
  --rpc-http-host="0.0.0.0" \
  --rpc-http-port=${RPC_PORT} \
  --rpc-http-cors-origins="*" \
  ${CONSENSUS_ARGS} \
  --host-allowlist="*" \
  --min-gas-price=0 \
  --p2p-port=${P2P_PORT} \
  --logging=WARN \
  > /tmp/besu-${NETWORK}.log 2>&1 &

echo $! > /tmp/besu-${NETWORK}.pid
echo "==> Besu ${NETWORK} started (PID: $(cat /tmp/besu-${NETWORK}.pid))"
echo "    RPC: http://localhost:${RPC_PORT}"
echo "    Log: /tmp/besu-${NETWORK}.log"

# ---- Wait for node to be ready --------------------------------
echo -n "Waiting for node to be ready"
for i in $(seq 1 30); do
  sleep 2
  if curl -s -X POST -H "Content-Type: application/json" \
     --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
     http://localhost:${RPC_PORT} | grep -q "result"; then
    echo ""
    echo "==> Node is READY on port ${RPC_PORT}"
    exit 0
  fi
  echo -n "."
done
echo ""
echo "ERROR: Node failed to start. Check /tmp/besu-${NETWORK}.log"
cat /tmp/besu-${NETWORK}.log | tail -30
exit 1
