#!/usr/bin/env bash
set -euo pipefail

# deploy_service publishes the dashboard and worker services.
deploy_service() {
  local target="${1:-staging}"
  echo "deploying service to ${target}"
  make build
  make publish
}

release_checklist() {
  echo "1. run tests"
  echo "2. deploy service"
  echo "3. verify metrics"
}

if [[ "${1:-}" == "--deploy" ]]; then
  deploy_service "${2:-staging}"
else
  release_checklist
fi
