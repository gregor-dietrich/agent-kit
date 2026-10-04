#!/usr/bin/env bash
# Sync .venv from uv.lock. uv is taken from PATH, then from .venv; when
# neither has it, the version uv.lock pins is bootstrapped with pip into a
# throwaway venv — never a curl|sh installer, never an unpinned uv.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if command -v uv >/dev/null 2>&1; then
	uv=uv
elif [[ -x .venv/bin/uv ]]; then
	uv=.venv/bin/uv
else
	pin=$(awk '/^\[/ { n = "" } /^name = "uv"$/ { n = 1 }
		n && /^version = / { gsub(/"/, "", $3); print $3; exit }' uv.lock)
	[[ -n "$pin" ]] || { echo "no uv pin in uv.lock" >&2; exit 1; }
	echo "uv not found; bootstrapping uv==$pin into .uv-bootstrap" >&2
	rm -rf .uv-bootstrap
	python3 -m venv .uv-bootstrap
	.uv-bootstrap/bin/pip install --quiet "uv==$pin"
	uv=.uv-bootstrap/bin/uv
fi
"$uv" sync --frozen
