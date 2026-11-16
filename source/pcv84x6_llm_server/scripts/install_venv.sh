#!/usr/bin/env bash
# Create the virtualenv and install runtime + test dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install fastapi uvicorn httpx pydantic
.venv/bin/pip install pytest pytest-asyncio
echo "venv ready: $(pwd)/.venv"
