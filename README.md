# RIDE

RIDE is the inference **Control Plane**. Request Throttling is one Controller type.
Ray is the process execution substrate: RIDE deploys independent Controller and
`vllm serve` jobs, observes them, and manages only its persisted owned jobs.
RIDE connects to an existing RayCluster. It never requires a new Coder template
or workspace per deployment. An existing owner-only Coder App is optional. RIDE's management API is not on the model request path.

先从 [已有 Ray 集群的命令行操作说明](docs/CLI_QUICKSTART.md) 开始。

## 项目成果与验收总索引

[RIDE × Request Throttling 一页总览](https://github.com/vLLM-HUST/request-throttling-controller/blob/main/docs/PROJECT_INDEX.md)
集中展示系统责任边界、官方迁移、三方真机性能、全程图、原始数据索引、
一键回收/报告及未完成项。RIDE 是控制面，Controller 的性能结果单独验收；
CPU/CI 和 payload 检查不冒充实际 NPU 端到端证据。

新增 Controller 见 [Controller 开发与接入指南](docs/CONTROLLER_DEVELOPMENT.md)。

安装部署见 [复用已有 RayCluster 的安装与部署脚本](docs/INSTALL_AND_DEPLOY.md)。

Current deployment authority: [existing-Ray deployment policy](docs/DEPLOYMENT_POLICY.md).
CPU tests are prerequisites; complete acceptance requires real NPU/model/control actions.

## Platform entry (v0.2)

```sh
python -m pip install '.[ray]'
ride start --ray-address http://127.0.0.1:8265

ride start model-service vllm --name model-main \
  --model /models/Qwen --endpoint http://model-host:8000 \
  --port 8000 --num-gpus 1

ride start controller request-throttling --name throttle-main \
  --backend http://model-host:8000 --endpoint http://controller-host:9000 \
  --port 9000 --executor ray

ride get model-services
ride get controllers
ride describe controller throttle-main
ride logs model-service model-main
ride stop controller throttle-main
ride start controller throttle-main
```

The endpoints must be reachable from the management process and clients;
`localhost` does not address another Ray node. GPU reservation uses
`--num-gpus`; Ascend custom resources use e.g.
`--resources '{"NPU": 1}'`, according to the actual Ray resource names.
CPU/GPU requirements and `--runtime-env` must match the deployed environment.
Model weights and pinned Controller dependencies must already exist in that
runtime. RIDE does not download weights or assume accelerator compatibility.

Names identify instances; `request-throttling` and `vllm` identify types.
Same-name same-configuration start is idempotent; different configuration is
rejected. YAML is not required. Optional `--config` currently reads JSON;
YAML parsing is not implemented. `ride serve --config examples/ride.json`
remains compatible. `ride start` runs the management process in the foreground.
Clients use `--address` or `RIDE_ADDRESS` to reach it.

Use `--model-service model-main` on Controller creation to require an owned
model service to be Ready and its endpoint to match the Controller backend.
Without that option, an external model backend is allowed. Stopping a
Controller leaves both owned and external model services running.

## Management API / UI

- `GET /healthz`: management process health.
- `GET /api/v1/status`: workspace identity, independent model and Controller states.
- `GET /api/v1/{controllers|model-services}`: list instances.
- `GET /api/v1/{kind}/{name}`: inspect an instance.
- `GET /api/v1/{kind}/{name}/logs`: owned Ray job logs.
- `POST /api/v1/{kind}/{name}/start`: create/start; JSON spec optional for existing instance.
- `POST /api/v1/{kind}/{name}/stop`: stop only that persisted owned job.

UI and CLI use the same API. Ray Running and service Ready are distinct; neither
proves effective control or performance improvement. Submission outcomes that
are uncertain retain the exact Job ID; a failed lookup does not create another
Job. Persistent `.ride/state.json` supports management restart/adoption.

## Current boundaries

Ray execution only; a local executor, generic third-party discovery, full common
control-loop contracts, graceful drain, high availability, authentication inside
the listener, and cross-Controller arbitration are not implemented. Restrict the
listener to the workspace and use owner-only Coder access. A trusted owner can
provide runtime environments and model arguments. Stop can interrupt in-flight
requests; it is not graceful drain.

The unvalidated extension-manager Bundle draft is excluded from the v0.2 wheel.
See [design](docs/FRAMEWORK_SPEC.md), [refactor acceptance](docs/PLATFORM_ENTRY_REFACTOR_20261010.md)
and [historical workspace acceptance](docs/WORKSPACE_E2E_ACCEPTANCE_20261010.md).

Standardized acceptance is built in: `ride verify --controller <instance> --model-service <instance> --output evidence.json`. Add `--lifecycle` to explicitly test stop/restore, `--model <served-name>` for a real inference, and `--baseline <before-restart.json>` to verify management restart adoption. See [acceptance contract](docs/ACCEPTANCE_CONTRACT.md). PASS only covers executed checks; NOT_RUN and performance scope remain explicit.

Coding agents and reviewers: follow [mandatory acceptance procedure](docs/ACCEPTANCE_PROCEDURE.md), using the plan and action templates in acceptance/.
