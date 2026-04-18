.PHONY: setup test run demo clean lint format check help

PYTHON := python
PIP := pip
PYTEST := pytest

# Default target
help:
	@echo "TruthCert + OpenClaw + Supermemory Stack"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  setup     Install dependencies"
	@echo "  test      Run all tests"
	@echo "  run       Start the certifier service"
	@echo "  demo      Run demo certification job"
	@echo "  lint      Run linter"
	@echo "  format    Format code"
	@echo "  check     Run all checks (lint + test)"
	@echo "  clean     Clean build artifacts"
	@echo "  keygen    Generate signing keys"

# Setup development environment
setup:
	$(PIP) install -e ".[dev]"
	@echo "Setup complete. Generate keys with: make keygen"

# Install production dependencies only
install:
	$(PIP) install -e .

# Run all tests
test:
	$(PYTEST) -v tests/ memory/tests/ --tb=short

# Run tests with coverage
test-cov:
	$(PYTEST) -v tests/ memory/tests/ --cov=certifier --cov=memory --cov-report=term-missing

# Start the certifier service
run:
	$(PYTHON) -m certifier.main

# Start with uvicorn for development
run-dev:
	uvicorn certifier.main:app --reload --host 0.0.0.0 --port 8000

# Run demo certification
demo:
	@echo "Running demo certification..."
	@if [ ! -f keys/private.key ]; then \
		echo "Generating keys first..."; \
		$(MAKE) keygen; \
	fi
	@export TRUTHCERT_SIGNING_KEY=$$(cat keys/private.key) && \
	export TRUTHCERT_PUBLIC_KEY=$$(cat keys/public.key) && \
	$(PYTHON) -m cli.tc certify examples/fixtures/sample_claims.jsonl --policy bronze
	@echo ""
	@echo "Demo complete. Check bundles/ directory for output."

# Generate signing keys
keygen:
	@mkdir -p keys
	$(PYTHON) -m cli.tc keygen --output keys
	@echo ""
	@echo "Keys generated in keys/ directory"
	@echo "Set environment variables:"
	@echo "  export TRUTHCERT_SIGNING_KEY=\$$(cat keys/private.key)"
	@echo "  export TRUTHCERT_PUBLIC_KEY=\$$(cat keys/public.key)"

# Run linter
lint:
	ruff check .

# Format code
format:
	ruff format .

# Run all checks
check: lint test

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf __pycache__/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Clean all generated files including bundles and logs
clean-all: clean
	rm -rf bundles/
	rm -rf logs/
	rm -rf memory.db
	rm -rf keys/

# Memory commands
memory-profile:
	$(PYTHON) -m cli.tc memory profile

memory-index:
	$(PYTHON) -m cli.tc memory index-codebase --path . --max-files 400

memory-wipe:
	@echo "This will delete all memory data!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] && \
	$(PYTHON) -m cli.tc memory wipe --yes

# Docker targets
docker-build:
	docker build -t truthcert:latest .

docker-run:
	docker run -p 8000:8000 -e TRUTHCERT_SIGNING_KEY truthcert:latest

docker-compose-up:
	docker-compose up -d

docker-compose-down:
	docker-compose down
