#!/usr/bin/env bash
# gate.sh — full quality gate for Python projects
# Run before handoff / push. Exits non-zero on first failure.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BOLD='\033[1m'
RESET='\033[0m'

step() { printf "\n${BOLD}▸ %s${RESET}\n" "$1"; }
pass() { printf "${GREEN}  ✓ %s${RESET}\n" "$1"; }
fail() { printf "${RED}  ✗ %s${RESET}\n" "$1"; exit 1; }

SRC="${SRC_DIR:-.}"
VENV_DIR="${VENV_DIR:-.venv}"
EXCLUDE_DIRS=".venv,node_modules,.mypy_cache,.pytest_cache"
TYPE_SRC="${TYPE_SRC_DIR:-src}"
if [ ! -d "$TYPE_SRC" ]; then
  TYPE_SRC="$SRC"
fi

# --- Venv: ensure active, create via uv if missing ---
step "virtual environment"
if [ -z "${VIRTUAL_ENV:-}" ]; then
  if [ ! -d "$VENV_DIR" ]; then
    if ! command -v uv &>/dev/null; then
      fail "no venv and uv not installed (pip install uv)"
    fi
    printf "  creating venv via uv…\n"
    uv venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  pass "activated $VENV_DIR"
else
  pass "venv already active ($VIRTUAL_ENV)"
fi

# --- Deps: install gate tools if missing ---
step "gate tool deps"
GATE_TOOLS=(flake8 isort autopep8 pyupgrade mypy pytest)
MISSING=()
for tool in "${GATE_TOOLS[@]}"; do
  if ! command -v "$tool" &>/dev/null; then
    MISSING+=("$tool")
  fi
done
if [ ${#MISSING[@]} -gt 0 ]; then
  printf "  installing: %s\n" "${MISSING[*]}"
  uv pip install "${MISSING[@]}"
  pass "installed missing tools"
else
  pass "all gate tools present"
fi

# --- Lint: flake8 ---
step "flake8 (style + quality)"
if flake8 "$SRC" --exclude "$EXCLUDE_DIRS" --max-line-length=120 --count --show-source --statistics; then
  pass "flake8"
else
  fail "flake8 found issues"
fi

# --- Import sorting: isort ---
step "isort (import order)"
if isort "$SRC" --check-only --diff --skip .venv --skip node_modules --skip .mypy_cache --skip .pytest_cache; then
  pass "isort"
else
  fail "isort: imports out of order (run: isort .)"
fi

# --- Formatting: autopep8 ---
step "autopep8 (PEP8 formatting)"
DIFF=$(autopep8 --recursive --diff --max-line-length=120 --exclude "$EXCLUDE_DIRS" "$SRC" 2>&1 || true)
if [ -z "$DIFF" ]; then
  pass "autopep8"
else
  printf "%s\n" "$DIFF"
  fail "autopep8: formatting issues (run: autopep8 --in-place --recursive .)"
fi

# --- Syntax upgrade: pyupgrade ---
step "pyupgrade (modern Python syntax)"
PYUP_FAIL=0
while IFS= read -r -d '' f; do
  if ! pyupgrade --py310-plus "$f" --keep-runtime-typing 2>/dev/null; then
    PYUP_FAIL=1
  fi
done < <(find "$SRC" -name '*.py' -not -path '*/.venv/*' -not -path '*/node_modules/*' -not -path '*/.mypy_cache/*' -not -path '*/.pytest_cache/*' -print0)
if [ "$PYUP_FAIL" -eq 0 ]; then
  pass "pyupgrade"
else
  fail "pyupgrade: syntax can be modernized"
fi

# --- Debug statements ---
step "debug statements (pdb / breakpoint / print)"
if grep -rn --include='*.py' -E '^\s*(import pdb|pdb\.set_trace|breakpoint\(\))' "$SRC" \
   --exclude-dir=.venv --exclude-dir=node_modules; then
  fail "debug statements found — remove before commit"
else
  pass "no debug statements"
fi

# --- Type checking: mypy ---
step "mypy (static type check)"
if mypy "$TYPE_SRC" --ignore-missing-imports --no-error-summary 2>/dev/null; then
  pass "mypy"
else
  fail "mypy found type errors"
fi

# --- Trailing whitespace ---
step "trailing whitespace"
if grep -rn --include='*.py' --include='*.yaml' --include='*.yml' --include='*.json' \
   ' $' "$SRC" --exclude-dir=.venv --exclude-dir=node_modules; then
  fail "trailing whitespace found"
else
  pass "no trailing whitespace"
fi

# --- Tests: pytest ---
step "pytest"
if pytest -q --tb=short 2>/dev/null; then
  pass "tests passed"
else
  fail "tests failed"
fi

printf "\n${GREEN}${BOLD}Gate passed ✓${RESET}\n"
