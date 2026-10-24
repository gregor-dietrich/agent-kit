# devkit's common.mk and python-uv.mk bring the targets; this project
# adds lint-shell, shellcheck over every tracked *.sh, to lint-repo,
# and keeps test syncing .venv first.
PROJECT := agent-kit
COVERAGE_FLOOR := 91
DEVKIT := $(shell ./devkitw path)
ifeq ($(DEVKIT),)
$(error devkitw failed; see its message above)
endif
include .devkit/make/common.mk
include .devkit/make/python-uv.mk

test: install

.PHONY: lint-shell
lint-repo: lint-shell
lint-shell: install ## shellcheck every tracked *.sh
	@[ -x .venv/bin/shellcheck ] || { echo "lint-shell: no \
	.venv/bin/shellcheck: either shellcheck-py has no wheel for this \
	platform (see AGENTS.md, Gates), or .venv lost it (rm -rf .venv && make \
	install)" >&2; exit 1; }
	SHELLCHECK_OPTS= .venv/bin/shellcheck --norc -- $$(git ls-files '*.sh')
