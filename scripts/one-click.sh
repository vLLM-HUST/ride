#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ne 3 || ( "$1" != deploy && "$1" != accept && "$1" != accept-policy && "$1" != local-start && "$1" != local-restart && "$1" != local-stop ) ]]; then
  echo 'Usage (run in cloud): one-click.sh deploy|accept|accept-policy|local-start|local-restart|local-stop PLAN_JSON EVIDENCE_DIRECTORY' >&2
  exit 2
fi
if [[ "$1" == local-start || "$1" == local-restart || "$1" == local-stop ]]; then
  exec "${RIDE_PYTHON:-python3}" "$root/scripts/local_controller.py" "$1" "$2" "$3"
fi
exec "${RIDE_PYTHON:-python3}" "$root/scripts/acceptance_entry.py" "$1" --plan "$2" --output "$3"
