> 当前部署边界：[复用已有 RayCluster](../reference/DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

> 本文涉及旧环境、旧入口或临时资源的内容为历史记录／早期规划，不是当前部署操作指南。已删除资源不得据此重建。

### 2026-10-10 实现与云端验收进展

RIDE v0.2 已实现统一的 start、get、describe、logs、stop，Controller 与模型服务为两个独立 Ray Job。CLI 与 UI 共用管理 API，实例配置冲突拒绝，重复启动去重，停止 Controller 不连带停止模型。实现已推送 GitHub main，提交 df179a2。

按用户最新要求，后续验证全部在 9450 云端执行，Web UI 使用 workspace 的 Coder App；本地转发端口已关闭。入口：https://coder.sage.org.ai:9450/@admin/ride-e2e-myc.main/apps/ride/ ，需要 admin 登录，不是平台共享实例。

7 项接口回归已在 9450 workspace 运行通过。模型通过 RIDE 的 model-service 命令提交，首次因缺 acl 环境失败，保留失败日志；显式补齐 CANN 路径后新实例加载成功，KV 154368 token。Request Throttling 随后已提交；真实请求和独立生命周期继续验收。提交成功、健康检查和性能结论分别记录，当前不宣称性能或完整闭环验收通过。
