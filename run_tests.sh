#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEST_STACK="${TEST_STACK:-baseline}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TEST_VENV_DIR="${TEST_VENV_DIR:-$SCRIPT_DIR/.venv-$TEST_STACK}"

case "$TEST_STACK" in
    minimum) TEST_REQUIREMENTS="$SCRIPT_DIR/requirements-test-min.txt" ;;
    baseline) TEST_REQUIREMENTS="$SCRIPT_DIR/requirements-test.txt" ;;
    *) echo "TEST_STACK must be minimum or baseline" >&2; exit 2 ;;
esac

"$PYTHON_BIN" -c 'import sys; sys.exit("Python 3.14 is required" if sys.version_info[:2] != (3, 14) else 0)'
if [ ! -x "$TEST_VENV_DIR/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$TEST_VENV_DIR"
fi
if ! "$TEST_VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
    "$TEST_VENV_DIR/bin/python" -m ensurepip --upgrade
fi
# Reinstall from the pins on every invocation so an old environment cannot silently
# keep a different HA stack. uv reuses cached wheels and already-correct installs.
"$TEST_VENV_DIR/bin/python" -m pip install --quiet uv==0.9.28
"$TEST_VENV_DIR/bin/uv" pip install --python "$TEST_VENV_DIR/bin/python" -r "$TEST_REQUIREMENTS"
cd "$SCRIPT_DIR"
"$TEST_VENV_DIR/bin/pytest" --tb=short -v "$@"
