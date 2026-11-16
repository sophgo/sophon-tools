#!/usr/bin/env bash
# Build the console. Requires node only at build time; the board runs the
# prebuilt dist/ and never needs node.
#
# sophon-tools adaptation: `npm ci` instead of `npm install`. `ci` installs
# exactly what web/package-lock.json pins and fails if the lockfile and
# package.json disagree, so two builds of one commit produce the same console.
# The lockfile is committed for exactly this reason (see .gitignore). It still
# runs only when node_modules is missing: an existing install is reused, and
# `ci` itself always wipes node_modules, so this keeps rebuilds cheap without
# ever resolving versions at build time on a fresh tree.
set -euo pipefail
cd "$(dirname "$0")/../web"
if [ ! -d node_modules ]; then
  [ -f package-lock.json ] || {
    echo "web/package-lock.json is missing: the console build is locked to it" >&2
    exit 2
  }
  npm ci --no-audit --no-fund
fi
npm run build
echo "built -> $(pwd)/dist"
