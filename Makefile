# Local commands for build milestones B1 to B4 (AGENTS.md section 12). Run from the repository root.
BACKEND := backend
VENV := $(BACKEND)/.venv/bin

.PHONY: up down seed-demo demo-reset web web-build web-test web-e2e web-check test test-unit test-integration check reset-test-db

up:
	$(BACKEND)/scripts/dev_up.sh

down:
	$(BACKEND)/scripts/dev_down.sh

# One invented tenant (controller, clerk, suppliers, POs, aliases) in matchdesk_dev; writes the files
# to upload to play-files/ (docs/PLAY.md). ARGS="--preload" also uploads and processes them (B3).
seed-demo:
	cd $(BACKEND) && .venv/bin/python scripts/seed_demo.py $(ARGS)

# Empty matchdesk_dev, restart the API and worker, and seed again (local synthetic data only).
demo-reset:
	$(BACKEND)/scripts/demo_reset.sh

# The web app (B4): Vite dev server on http://127.0.0.1:5173, /api/v1 proxied to the API on 8101.
web: web/node_modules
	cd web && npm run dev

web/node_modules: web/package.json
	cd web && npm install && touch node_modules

web-build: web/node_modules
	cd web && npm run build

web-test: web/node_modules
	cd web && npm test

# E2E-01 and the accessibility scan, headless in the installed Google Chrome; needs make up and make web.
web-e2e: web/node_modules
	cd web && npm run e2e

# Type check, lint, unit tests and production build of the web app.
web-check: web/node_modules
	cd web && npm run typecheck && npm run lint && npm test && npm run build

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
