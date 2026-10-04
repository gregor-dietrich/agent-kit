.PHONY: help install test

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

install: ## Sync .venv from uv.lock (bootstraps the pinned uv if missing)
	@scripts/install.sh

test: install ## Run the hook tests
	.venv/bin/pytest
