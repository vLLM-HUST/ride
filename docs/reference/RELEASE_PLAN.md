> 当前部署边界：[复用已有 RayCluster](DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

> 本文涉及旧环境、旧入口或临时资源的内容为历史记录／早期规划，不是当前部署操作指南。已删除资源不得据此重建。

# RIDE 发布路线

RIDE 是推理系统 Control Plane；Request Throttling 是其中一个 Controller。性能优先，复用程度与适配层大小不是验收目标。

## 第一阶段：开发者预览

发布独立仓库与独立目录条目。描述为 workspace 内运行的控制面开发框架；当前支持 Controller 生命周期和观察，完整 State / Decision / Actuation / Feedback 尚未完成。不得以完整平台描述原型。

统一入口为 `ride serve --config <path>`，配置选择 Controller。Web UI 通过当前 workspace 的 Coder App 暴露，Ray 是执行后端，模型引擎生命周期独立。不得将用户实例放在 Coder 平台共享 `/ride/` 路径。

发布前门禁：从干净环境安装 wheel；校验独立 RIDE Bundle 的官方 Manifest 0.3；执行真实 workspace + Ray + Request Throttling + 模型请求闭环；核验页面展示实际实例、来源和状态；验证幂等启动、停止只影响自有 Controller、引擎保留及重新启动。失败保留日志，不将 health 200 等同于有效控制。

当前扩展接入草稿仍引用旧实验版 Manager，必须按官方 extension-manager 的当前契约修正并通过验证后再发布，不直接上线草稿。

## 第二阶段：形成可复用开发范式

以 Request Throttling 提供可复制的 Controller 示例，定义配置、状态观测、Decision、Actuation、Feedback、生命周期、权限和失败恢复契约。用第二个独立 Controller 检验契约能否复用；不要从单个 Router 推定所有 Controller 适用。

交付包含安装与启动、架构图、开发示例、接口规范、版本兼容表、运行来源、原始验收记录。Controller 性能报告独立，不能把 Controller 收益直接归因于 RIDE。

## 第三阶段：服务化

在 workspace 版本稳定后再实现身份授权、项目与实例管理、审计、凭据管理、配额及高可用。服务化部署沿用同一 Controller 契约，不另造一套启动方式。各 workspace 实例隔离；Coder 负责统一入口，RIDE 负责控制面。

## 对外展示

RIDE 独立条目链接 RIDE 仓库，Request Throttling 独立条目链接其仓库；相互说明 control plane 与 controller 的关系。优先提供一个可实际操作的端到端示例，再推广 Controller 开发接口。尚未验收能力明确标注 pending。
