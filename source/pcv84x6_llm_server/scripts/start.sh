#!/usr/bin/env bash
# Start the service in the foreground (development / manual use).
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m app.main "$@"
