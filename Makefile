# Local commands for build milestone B1 (AGENTS.md section 12). Run from the repository root.
BACKEND := backend
VENV := $(BACKEND)/.venv/bin

.PHONY: up down test test-unit test-integration check reset-test-db

up:
	$(BACKEND)/scripts/dev_up.sh

down:
	$(BACKEND)/scripts/dev_down.sh

# Unit and integration suites. Integration tests drop and re-migrate matchdesk_test first.
test:
	cd $(BACKEND) && .venv/bin/pytest -q

test-unit:
	cd $(BACKEND) && .venv/bin/pytest -q tests/unit

test-integration:
	cd $(BACKEND) && .venv/bin/pytest -q tests/integration

# Lint, format check, type check, import boundaries, top-level import rule, float lint.
check:
	cd $(BACKEND) && .venv/bin/ruff check src tests migrations scripts \
	  && .venv/bin/ruff format --check src tests migrations scripts \
	  && .venv/bin/mypy \
	  && .venv/bin/lint-imports \
	  && .venv/bin/python scripts/check_imports.py \
	  && .venv/bin/python scripts/check_no_float.py
