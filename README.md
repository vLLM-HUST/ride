# RIDE

RIDE is the inference **Control Plane**. **Request Throttling is one Controller within RIDE**, not another name for RIDE. The current prototype implements workspace-owned controller lifecycle and observation, not the complete State / Decision / Actuation / Feedback framework. Run management inside your Coder workspace; its Coder App proxies the Web UI. Ray runs controllers as separate jobs. Model engines have independent lifecycles.

```sh
python -m pip install '.[ray]'
ride serve --config examples/ride.json --listen 0.0.0.0:19100
```

The first supported controller is Request Throttling Controller. Install its pinned upstream dependencies in the Ray runtime before starting it. Configuration declares `deployment: ray`, `workspace`, `state_file`, `ray_address`, and controllers with `id`, `entrypoint: request-throttling`, `backend`, `endpoint`, `listen`, `runtime_env`, and `resources`. Set `autostart: true` for startup on launch; otherwise use the UI.

- `GET /healthz`: management process health.
- `GET /api/v1/status`: Ray job state, controller identity, backend health and programs.
- `POST /api/v1/controllers/{id}/start`: idempotent while the owned job is running or pending.
- `POST /api/v1/controllers/{id}/stop`: stops only the persisted controller job.

Use owner-only Coder App exposure, a persistent workspace state directory, and a dedicated Ray cluster. Do not expose the unauthenticated management listener publicly. This initial implementation has one management writer; it is not a high-availability or multi-tenant service.

See [workspace acceptance](docs/WORKSPACE_E2E_ACCEPTANCE_20261010.md) for measured results and remaining scope.
