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

Mandatory acceptance procedure: docs/ACCEPTANCE_PROCEDURE.md.
Before side effects, freeze a filled acceptance/plan-template.json and publish/read back the requested plan.
Every executed action records command, expectation, observation, exit status and evidence hashes.
Missing evidence is NOT_RUN/BLOCKED, never PASS. Never change thresholds after seeing results.
New shared RayCluster is allowed only by explicit user instruction; record the instruction. It does not authorize Coder templates/workspaces.
Do not infer full acceptance from a narrow script PASS. Review missing negative cases, adoption and real control semantics before claiming completion.

Cloud deployment/acceptance entry: scripts/one-click.sh deploy|accept PLAN_JSON EVIDENCE_DIRECTORY.
Extend this entry for missing gates; do not bypass it with undocumented manual recovery.
Exit 3 / INCOMPLETE is unfinished acceptance, never PASS.
