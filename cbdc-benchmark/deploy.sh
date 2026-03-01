#!/usr/bin/env bash
# CBDC Benchmark — One-command entry point
# Usage: ./deploy.sh [--teardown] [--benchmark-only] [--consensus poa|qbft|both]
exec "$(dirname "$0")/scripts/deploy.sh" "$@"
