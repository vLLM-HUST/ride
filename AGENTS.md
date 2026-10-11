# RIDE project execution rules

Read docs/DEPLOYMENT_POLICY.md before deployment or acceptance.
Reuse an existing RayCluster; deliver installation and deployment commands/scripts.
Do not create Coder templates/workspaces, RayClusters, gateways or PVCs as a side effect of app acceptance.
A platform resource change requires explicit authorization for that concrete change.
RIDE manages only its recorded Controller/model Jobs. Do not clean up the reused cluster.
CPU UT/Mock/integration checks are prerequisites, not complete end-to-end acceptance.
End-to-end acceptance requires real NPU vLLM requests, actual Controller action, output/state/log checks and stop/restore.
Web UI is optional, never a prerequisite to delivering CLI deployment.
Preserve historical evidence but label obsolete infrastructure procedures as historical.
