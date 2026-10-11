#!/usr/bin/env bash
set -euo pipefail
# Install RIDE from this checkout without touching Coder, Kubernetes or Ray.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${1:-$PWD/.ride-venv}"
python3 -m venv --system-site-packages "$venv"
"$venv/bin/python" -m pip install --no-build-isolation "$root[ray]" "${@:2}"
printf 'RIDE installed. Activate with: source %q/bin/activate\n' "$venv"
