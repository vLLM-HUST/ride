# RIDE

RIDE is the inference **Control Plane**. Request Throttling is one Controller type.
Ray is the process execution substrate: RIDE deploys independent Controller and
`vllm serve` jobs, observes them, and manages only its persisted owned jobs.
RIDE connects to an existing RayCluster. It never requires a new Coder template
or workspace per deployment. An existing owner-only Coder App is optional. RIDE's management API is not on the model request path.

先从 [已有 Ray 集群的命令行操作说明](docs/guides/CLI_QUICKSTART.md) 开始。

## 独立 Controller 与公共 SDK（0.3.2 开发分支）

RIDE 提供两部分：供各个 Controller 导入的轻量 `ride.sdk` 库，以及负责进程和模型生命周期的管理服务。每个 Controller 在自己的仓库实现策略、独立安装和发布；通过公开 API 协作。Ray 运行这些独立进程和模型，平台提供已有集群。新增策略不需要复制 RIDE，也不需要把策略写进 RIDE 核心。

| 项目 | 自己负责什么 | 交给 RIDE 什么 |
|---|---|---|
| [Request Throttling](https://github.com/vLLM-HUST/request-throttling-controller/tree/codex/independent-request-controller) | 请求限流、多轮任务归属、请求排空 | 独立进程托管、状态与日志 |
| [Instance Controller](https://github.com/yancanmao/instance-controller) | 何时扩缩容、Ready 后激活、请求和 KV 双排空 | 通过 SDK 启停准确的模型 Job |
| [KV Controller](https://github.com/yancanmao/kv-controller) | KV 能力查询、动作验证和排空保护 | 进程托管、配置身份与日志 |

Controller 只导入公共 `ride.sdk`，不导入彼此的策略实现。导入 SDK 不加载 Ray、Torch 或 vLLM，不启动服务。插件通过 `ride.controllers` 注册，遵守统一配置、身份与健康接口；策略循环由独立包运行。

当前已完成独立包的软件检查，以及真实模型的多轮请求、扩缩容、排空和有界恢复验证；完整收益验收仍在进行。当前 KV 后端只读，实际复制不支持；限流层仅支持空状态重启，不承诺非空状态恢复或高可用。详细边界、实际证据和下一项以[统一路线图](docs/architecture/CONTROLLER_ROADMAP.md)为准。

[公共 SDK](docs/guides/SDK.md) · [开发契约与接入方式](docs/guides/CONTROLLER_DEVELOPMENT.md) · [系统设计与可编辑架构图](docs/architecture/INDEPENDENT_CONTROLLERS.md) · [中长期规划](docs/PROJECT_PLAN.md) · [效果验证契约](docs/architecture/CONTROLLER_EVALUATION.md)

## 项目成果与验收总索引

[RIDE × Request Throttling 一页总览](https://github.com/vLLM-HUST/request-throttling-controller/blob/main/docs/PROJECT_INDEX.md)
记录历史请求控制实验的系统责任边界、官方迁移、真机结果、图与原始数据索引，
以及一键回收/报告及未完成项；它不是上述独立 KV/实例控制的收益验收。RIDE 是控制面，Controller 的性能结果单独验收；
CPU/CI 和 payload 检查不冒充实际 NPU 端到端证据。

新增 Controller 见 [Controller 开发与接入指南](docs/guides/CONTROLLER_DEVELOPMENT.md)。

安装部署见 [复用已有 RayCluster 的安装与部署脚本](docs/guides/INSTALL_AND_DEPLOY.md)。

[指定机器一键部署](docs/guides/MACHINE_DEPLOYMENT.md)复用 Ray 官方 on-premise
launcher，再托管管理服务、模型和 Controller。固定提交已完成双 devbox、双
TP1 的 9 次真实生成、管理接管和停止隔离；最新 0.3.3 集成通过 101 项软件检查，
尚未重跑 NPU。两个 devbox 同属一台物理主机，不代表跨物理主机或性能验收。

Current deployment authority: [existing-Ray deployment policy](docs/reference/DEPLOYMENT_POLICY.md).
CPU tests are prerequisites; complete acceptance requires real NPU/model/control actions.

## Compatible platform CLI

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

Ray execution manages both Controller and model Jobs. The local executor manages
owned Controller processes only; model lifecycle remains external in that mode.
Third-party discovery and the public health/identity/configuration contract are
implemented. Policy algorithms and their state remain in the independent packages.
High availability, authentication inside the management listener, and a general
cross-Controller policy arbiter are not implemented. Restrict the listener to the
workspace and use owner-only Coder access. A trusted owner can provide runtime
environments and model arguments. Generic stop can interrupt in-flight requests;
the Instance Controller explicitly coordinates request/KV drain before model stop.

The unvalidated extension-manager Bundle draft remains excluded from the wheel.
See [design](docs/reference/FRAMEWORK_SPEC.md), [refactor acceptance](docs/archive/PLATFORM_ENTRY_REFACTOR_20261010.md)
and [historical workspace acceptance](docs/archive/WORKSPACE_E2E_ACCEPTANCE_20261010.md).

Standardized acceptance is built in: `ride verify --controller <instance> --model-service <instance> --output evidence.json`. Add `--lifecycle` to explicitly test stop/restore, `--model <served-name>` for a real inference, and `--baseline <before-restart.json>` to verify management restart adoption. See [acceptance contract](docs/reference/ACCEPTANCE_CONTRACT.md). PASS only covers executed checks; NOT_RUN and performance scope remain explicit.

Coding agents and reviewers: follow [mandatory acceptance procedure](docs/reference/ACCEPTANCE_PROCEDURE.md), using the plan and action templates in acceptance/.
