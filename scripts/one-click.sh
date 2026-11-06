#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ge 3 && ( "$1" == machines-validate || "$1" == machines-up || "$1" == machines-status || "$1" == machines-stop || "$1" == machines-restart ) ]]; then
  exec "${RIDE_PYTHON:-python3}" -m ride.deployment "${1#machines-}" "${@:2}"
fi
if [[ $# -eq 3 && ( "$1" == local-start || "$1" == local-stop ) ]]; then
  exec "${RIDE_PYTHON:-python3}" "$root/scripts/local_controller.py" "$1" "$2" "$3"
fi
if [[ $# -ne 3 || ( "$1" != deploy && "$1" != accept && "$1" != accept-policy && "$1" != accept-adoption ) ]]; then
  echo 'Usage (run in cloud): one-click.sh deploy|accept|accept-policy|accept-adoption PLAN_JSON EVIDENCE_DIRECTORY' >&2
  exit 2
fi
exec "${RIDE_PYTHON:-python3}" "$root/scripts/acceptance_entry.py" "$1" --plan "$2" --output "$3"
