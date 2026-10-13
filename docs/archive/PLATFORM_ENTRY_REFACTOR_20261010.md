> 当前部署边界：[复用已有 RayCluster](../reference/DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

> 本文涉及旧环境、旧入口或临时资源的内容为历史记录／早期规划，不是当前部署操作指南。已删除资源不得据此重建。

# RIDE 平台入口重构 · 2026-10-10

RIDE 是 Control Plane，Ray 是执行底座，Controller 与模型服务是独立进程。v0.2 将 CLI/API、类型描述和运行层拆分，保持 `ride serve` 兼容。

实现：`ride start`、`start controller`、`start model-service`、`get`、`describe`、`logs`、`stop`；CLI/UI 共用 API。类型名与实例名分离，持久化实例配置与所属 Job，冲突拒绝、启动幂等和不确定提交去重。模型服务使用 `vllm serve`，资源与环境显式传入；模型挂载与依赖安装仍需部署环境提供。模型/Controller 分别观测，停止一个不会停止另一个。

源码：src/ride/registry.py（进程描述）、runtime.py（实例与 Ray 生命周期）、server.py（API）、__main__.py（CLI）、index.html（UI）。Ray 资源参数从实例规格传入，地址必须明确可达，不能推断 localhost 在不同 Job 间有效。

验证：7 项 unittest 通过；从 wheel 安装到独立环境、使用已安装模块重复通过 7 项。测试是真实 HTTP 和 CLI，Ray 客户端使用测试替身，因此不是硬件证据。覆盖跨类型同名隔离、重启接管、配置冲突、未知提交去重、未就绪依赖阻断、日志与跨源拒绝。

自有 admin/ride-e2e-myc 在本轮检查时已停止，RayCluster 与 Pod 均不存在，原因未归因。恢复同一自有 workspace 用于真机验收，不触碰 9443 性能扫描。新硬件结果在后续补充，不能继承历史 smoke 或性能 PASS。

发布边界：不包含尚未验证的 extension-manager Bundle 草稿；当前 optional config 为 JSON，不冒称 YAML 已实现；无本地执行后端、通用 plugin discovery、HA、内部认证、优雅 drain 或完整公共控制闭环。

真机阶段：管理进程已作为独立 Ray Job 运行。首次模型 Job 因 `ModuleNotFoundError: No module named acl` 失败，原始日志保留在 results/platform-v02；显式补齐 CANN Python 路径后使用新实例 model-cann，未覆盖失败实例。本次不是性能测试，尚待模型 Ready 与 Controller 请求/生命周期验收。
