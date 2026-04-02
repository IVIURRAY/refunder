#!/usr/bin/env bash
# Bootstrap local development environment for RefundAgent using uv.
# Run from the refundagent/ directory.

set -euo pipefail

echo "==> Setting up RefundAgent local development environment"

# Check uv is installed
if ! command -v uv &>/dev/null; then
    echo "==> uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo "==> uv $(uv --version) found"

# Sync all dependencies (creates .venv automatically)
echo "==> Installing dependencies with uv sync"
uv sync

# Copy .env if not exists
if [ ! -f ".env" ]; then
    echo "==> Creating .env from .env.example"
    cp .env.example .env
    echo "    Edit .env with your configuration before running."
fi

# Check PostgreSQL
if command -v psql &>/dev/null; then
    echo "==> PostgreSQL CLI found"
    echo "    To set up the database, run:"
    echo "    createdb refundagent"
    echo "    psql -U refundagent -d refundagent -f src/db/migrations/001_initial.sql"
else
    echo "    WARNING: psql not found. Install PostgreSQL to run the database locally."
fi

echo ""
echo "==> Setup complete."
echo "    Run CLI:   uv run refundagent claims list"
echo "    Run tests: uv run pytest tests/ -v"
