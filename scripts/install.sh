#!/usr/bin/env bash
set -euo pipefail
# Install RIDE from this checkout without touching Coder, Kubernetes or Ray.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${1:-$PWD/.ride-venv}"
extra='ray'
if [[ "${RIDE_EXECUTOR:-ray}" == local ]]; then
  extra=''
elif [[ "${RIDE_EXECUTOR:-ray}" != ray ]]; then
  echo 'RIDE_EXECUTOR must be ray or local' >&2; exit 2
fi
requirement="$root"
if [[ -n "$extra" ]]; then requirement="$root[$extra]"; fi
python3 -m venv --system-site-packages "$venv"
"$venv/bin/python" -m pip install --no-build-isolation "$requirement" "${@:2}"
printf 'RIDE installed. Activate with: source %q/bin/activate\n' "$venv"
