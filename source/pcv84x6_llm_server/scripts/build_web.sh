#!/usr/bin/env bash
# Build the console. Requires node only at build time; the board runs the
# prebuilt dist/ and never needs node.
set -euo pipefail
cd "$(dirname "$0")/../web"
if [ ! -d node_modules ]; then
  npm install --no-audit --no-fund
fi
npm run build
echo "built -> $(pwd)/dist"
