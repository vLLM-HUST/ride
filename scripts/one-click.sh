#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ne 3 || ( "$1" != deploy && "$1" != accept && "$1" != accept-policy ) ]]; then
  echo 'Usage (run in cloud): one-click.sh deploy|accept|accept-policy PLAN_JSON EVIDENCE_DIRECTORY' >&2
  exit 2
fi
exec "${RIDE_PYTHON:-python3}" "$root/scripts/acceptance_entry.py" "$1" --plan "$2" --output "$3"
