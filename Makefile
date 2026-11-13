# Local commands for build milestones B1 to B9 (AGENTS.md section 12). Run from the repository root.
BACKEND := backend
VENV := $(BACKEND)/.venv/bin

.PHONY: up down sandbox-up seed-sandbox qbo-capture seed-demo demo-reset demo-email demo-po-change operator-code web web-build web-test web-e2e web-check test test-unit test-integration check reset-test-db

up:
	$(BACKEND)/scripts/dev_up.sh

down:
	$(BACKEND)/scripts/dev_down.sh

# B11: restart the local stack with the web app on http://localhost:5173, the origin of the Intuit
# redirect URI, so the session cookie set at sign-in is sent back when Intuit returns (cookies are
# host-bound: localhost and 127.0.0.1 are different hosts). The demo works the same on this origin.
sandbox-up:
	$(BACKEND)/scripts/dev_down.sh
	MATCHDESK_APP_BASE_URL=http://localhost:5173 $(BACKEND)/scripts/dev_up.sh

# B11: a second synthetic tenant in Intuit mode (no connection; its controller connects on S-04).
seed-sandbox:
	cd $(BACKEND) && MATCHDESK_APP_BASE_URL=http://localhost:5173 .venv/bin/python scripts/seed_sandbox.py

# B11, T-1.1.1: read-only capture of the connected sandbox company to backend/var/qbo-capture/.
qbo-capture:
	cd $(BACKEND) && .venv/bin/python scripts/qbo_sandbox_capture.py $(ARGS)

# One invented tenant (controller, clerk, suppliers, POs, aliases) in matchdesk_dev; writes the files
# to upload to play-files/ (docs/PLAY.md). ARGS="--preload" also uploads and processes them (B3).
seed-demo:
	cd $(BACKEND) && .venv/bin/python scripts/seed_demo.py $(ARGS)

# Empty matchdesk_dev, restart the API and worker, and seed again (local synthetic data only).
demo-reset:
	$(BACKEND)/scripts/demo_reset.sh

# B7: two synthetic signed emails to the local intake webhook (one accepted, one held).
demo-email:
	cd $(BACKEND) && .venv/bin/python scripts/demo_email.py

# B9: read QuickBooks again from recorded responses taken after a change (S-10 banner; demo only).
demo-po-change:
	cd $(BACKEND) && .venv/bin/python scripts/demo_po_change.py

# B7: the current one-time code of the local demo operator (development only).
operator-code:
	cd $(BACKEND) && .venv/bin/python scripts/operator_code.py $(EMAIL)

# The web app (B4): Vite dev server on http://127.0.0.1:5173, /api/v1 proxied to the API on 8101.
web: web/node_modules
	cd web && npm run dev

web/node_modules: web/package.json
	cd web && npm install && touch node_modules

web-build: web/node_modules
	cd web && npm run build

web-test: web/node_modules
	cd web && npm test

# E2E-01 and the accessibility scan, headless in the installed Google Chrome, on Playwright's own stack:
# database matchdesk_e2e, API 8102, worker, web 5174 (backend/scripts/e2e_stack.sh). Needs PostgreSQL and Mailpit;
# fails if any matchdesk_dev row count changed.
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
