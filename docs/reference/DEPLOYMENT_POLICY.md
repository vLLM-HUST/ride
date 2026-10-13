> 当前统一开发契约：[RIDE 开发与变更契约](DEVELOPMENT_CONTRACT.md)。旧文中“新建集群”必须通过 Coder admin 标准 RayCluster 工作区；不得直接创建 Kubernetes RayCluster。用户已授权按契约继续；门禁实现与验收状态须分别记录。

# 部署与验收边界（当前规范）

更新时间：2026-10-11。此文档优先于历史验收记录和早期规划。

- RayCluster 由用户或平台预先提供。默认复用已有集群。
- RIDE 提供安装、管理进程启动、Controller／模型 Ray Job 部署、状态、日志、停止和恢复。
- Controller 实现自己的策略与观测接口，不管理平台资源。
- 应用开发、部署和验收不得擅自创建 Coder template、workspace、RayCluster、平台网关或持久卷。
  如确需改变平台资源，必须说明缺口并取得该具体变更的授权；“做端到端验收”不等于授权建设平台。
- Coder 工作区与 owner-only App 可以复用已有入口；Web UI 不是 CLI 部署的前置条件。
- CPU UT、Mock 与生命周期集成测试只算前置检查，不得称完整端到端验收。
- 完整端到端验收必须使用真实 NPU、真实 vLLM、实际 Controller 控制动作和真实模型请求，
  核对输出、控制状态、日志、停止隔离及恢复；性能收益另需有效基线对照。
- 清理只针对本次 owned Jobs。默认不停止或删除复用的集群、工作区、模板或卷。
- 历史创建临时模板／工作区的记录保留作追溯，不作为今后部署步骤。

唯一安装部署入口：[INSTALL_AND_DEPLOY](../guides/INSTALL_AND_DEPLOY.md)。
独立 Controller：[开发指南](../guides/CONTROLLER_DEVELOPMENT.md)、[Demo 规范](https://github.com/vLLM-HUST/ride-controller-demo/blob/main/DEVELOPMENT.md)。

现有 disposable CPU CI 会创建临时 Kubernetes Pod 和内部测试 Ray，属于历史测试设施，
不属于 RIDE 用户部署方案，也不证明 NPU 端到端验收。后续复用已有 Ray 的验收应走
Controller 验收脚本，不能直接沿用环境创建脚本。硬件 workflow 的专用工作区配置也是历史配置，
不得因文件仍在就自动恢复已删除工作区。
