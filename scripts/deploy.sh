#!/usr/bin/env bash
set -euo pipefail
# Foreground management service connected to an EXISTING Ray Jobs endpoint.
if [[ $# -lt 2 || $# -gt 4 ]]; then
  echo 'Usage: deploy.sh RAY_JOBS_URL STATE_FILE [WORKSPACE_NAME] [LISTEN_ADDRESS]' >&2
  exit 2
fi
ray_address="$1"
state_file="$2"
workspace="${3:-${CODER_WORKSPACE_NAME:-ride}}"
listen="${4:-127.0.0.1:19100}"
python - "$ray_address" <<'PY'
import sys,json
from urllib.request import urlopen
with urlopen(sys.argv[1].rstrip('/')+'/api/version',timeout=10) as response:
    version=json.load(response)
print('Existing Ray endpoint reachable:', version)
PY
exec ride start --ray-address "$ray_address" --state-file "$state_file" \
  --workspace "$workspace" --listen "$listen"
