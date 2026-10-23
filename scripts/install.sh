#!/usr/bin/env bash
# Sync .venv from uv.lock. uv is taken from PATH, then from .venv; when
# neither has it, the version uv.lock pins is bootstrapped with pip into a
# throwaway venv — never a curl|sh installer, never a uv whose wheel
# uv.lock does not hash.
set -euo pipefail
CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

if command -v uv >/dev/null 2>&1; then
	uv=uv
elif [[ -x .venv/bin/uv ]]; then
	uv=.venv/bin/uv
else
	reqs=$(awk '/^\[/ { n = "" } /^name = "uv"$/ { n = 1 }
		n && /^version = / { gsub(/"/, "", $3); v = $3 }
		n && /\.whl"/ && match($0, /sha256:[0-9a-f]+/) {
			h = h " --hash=" substr($0, RSTART, RLENGTH)
		}
		END { if (v != "" && h != "") print "uv==" v h }' uv.lock)
	[[ -n "$reqs" ]] || { echo "no uv pin or wheel hashes in uv.lock" >&2; exit 1; }
	echo "uv not found; bootstrapping ${reqs%% *} into .uv-bootstrap" >&2
	rm -rf .uv-bootstrap
	python3 -m venv .uv-bootstrap
	echo "$reqs" >.uv-bootstrap/requirements.txt
	.uv-bootstrap/bin/pip install --quiet --require-hashes \
		--only-binary=:all: -r .uv-bootstrap/requirements.txt
	uv=.uv-bootstrap/bin/uv
fi
"$uv" sync --frozen
