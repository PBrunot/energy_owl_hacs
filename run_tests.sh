#!/usr/bin/env bash
set -e

VENV_DIR="$(dirname "$0")/.venv"

# Create venv if not present
if [ ! -f "$VENV_DIR/bin/pytest" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "Installing pytest-homeassistant-custom-component (this takes a few minutes)..."
    "$VENV_DIR/bin/pip" install --quiet pytest-homeassistant-custom-component
    echo "Done."
fi

echo ""
echo "Running tests..."
"$VENV_DIR/bin/pytest" --tb=short -v "$@"
