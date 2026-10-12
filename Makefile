# devkit's common.mk brings help, check, hooks, gate and the repository
# gates (lint-repo). Its python-uv.mk is not included: install and test
# stay this project's own.
PROJECT := agent-kit
DEVKIT := $(shell ./devkitw path)
ifeq ($(DEVKIT),)
$(error devkitw failed; see its message above)
endif
include .devkit/make/common.mk

.PHONY: install test

install: ## Sync .venv from uv.lock (bootstraps the pinned uv if missing)
	@scripts/install.sh

test: install ## Run the test suite
	.venv/bin/pytest
