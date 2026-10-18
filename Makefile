# devkit's common.mk brings help, check, hooks, gate and the repository
# gates (lint-repo). Its python-uv.mk is not included: install and test
# stay this project's own, as is lint-shell.
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

.PHONY: lint-shell
lint-repo: lint-shell
lint-shell: install ## shellcheck every tracked *.sh
	@[ -x .venv/bin/shellcheck ] || { echo "lint-shell: no \
	.venv/bin/shellcheck: either shellcheck-py has no wheel for this \
	platform (see AGENTS.md, Gates), or .venv lost it (rm -rf .venv && make \
	install)" >&2; exit 1; }
	SHELLCHECK_OPTS= .venv/bin/shellcheck --norc -- $$(git ls-files '*.sh')
