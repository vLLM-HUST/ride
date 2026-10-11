> 当前部署边界：[复用已有 RayCluster](DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

# RIDE 标准验收契约

RIDE 的验收入口为 `ride verify`，标准位于 `ride.acceptance.CONTRACT`，报告版本为 `ride.acceptance/v1`。每项固定输出 PASS、FAIL、NOT_RUN，包含判据、时间、被测实例、实际 Job ID、原始状态、请求/响应及服务日志。报告 PASS 表示执行的检查通过；complete=false 表示仍有部署/生命周期检查未运行。性能始终单独验收，不能从健康检查推导。

## 在云端 workspace 内执行

```sh
ride verify --controller throttle-main --model-service model-cann \
  --lifecycle --model qwen2.5-14b --output acceptance-before-restart.json
```

普通 verify 不主动改变服务；显式 `--lifecycle` 才对选中的 Controller 执行重复启动、停止和恢复。先确认模型/Controller 都就绪且依赖地址一致；否则主动检查 NOT_RUN。停止 Controller 后检查原模型 Job ID 保持且 Ready；恢复后检查新的 Controller Job Ready。普通真实请求验证非空响应及正 token 数，不冒称 program 的暂停/恢复等调度语义已经验收。无自动性能压测、不接触未登记实例、不重启 workspace/集群。

## 管理进程重启接管

仅重启明确属于本工作区的 RIDE 管理 Job，保留 state_file。仓库脚本 `scripts/restart_owned_control_plane.py` 要求 deployment 和 ssh-host，核对完整原 entrypoint 才停止管理 Job，保留原日志并提交相同配置的新管理 Job；不停止模型和 Controller。

新管理服务可用后，在同一云端 workspace 执行：

```sh
ride verify --controller throttle-main --model-service model-cann \
  --model qwen2.5-14b --baseline acceptance-before-restart.json \
  --output acceptance-after-restart.json
```

adoption PASS 必须同时满足：管理进程 PID 改变、持久化 run_id 不变、选中模型和 Controller 的 Job ID 全部不变且均 Ready。baseline 必须来自同一被测实例；任一差异 FAIL。NOT_RUN 不转成 PASS。报告保留重启前后身份与日志，生命周期前段和重启后段分开，不伪装单次全通过。

## 能力边界

当前通用层验收控制面、模型、依赖、幂等、生命周期隔离、真实普通请求和重启接管。Controller 调度语义、全部 program 的正确性/公平性、同输入端到端性能、网页交互与认证、安全边界、整 workspace/PVC 恢复仍需专项证据，不能用本契约替代。当前内置 Request Throttling 与 vLLM，外部 Controller 可通过 ride.controllers 适配器注册；Demo 已完成真实 NPU 请求与控制动作验收。

所有执行验收在 9450 云端进行。Web 验收使用 workspace Coder App，无本地端口转发。开发机器只用于编辑和收回证据。

完整标准目录还包含 program_semantics、source_identity、web_ui、access_boundary 和 performance。这些专项没有被 verify 自动执行时一律 NOT_RUN；complete 仅表示 deployment_checks 全部通过，不等于全部专项已通过。源码/调度/性能不能只因为部署检查通过而升级为通过。

本轮 9450 实测：生命周期阶段 8 项 PASS；重启后接管阶段 adoption PASS，管理 PID 11833→12636，run_id 不变，Controller Job 后缀 7a583b86 与模型 Job 后缀 212d5f7c 均保留且 Ready。重启前后真实请求通过。11 项云端 unittest PASS；两阶段原始报告位于 results/platform-v02/acceptance-before-restart.json 与 acceptance-after-restart.json，云端原件保留在验收 workspace。未执行专项不补填。
