> 当前部署边界：[复用已有 RayCluster](../reference/DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

> 本文涉及旧环境、旧入口或临时资源的内容为历史记录／早期规划，不是当前部署操作指南。已删除资源不得据此重建。

# Workflow 验收

日常回归不需要 GPU/NPU。`.github/workflows/contract.yml` 在 main push 或手动触发时，在专用 9450 runner 上安装当前提交并跑接口回归，然后运行真实 Ray、真实 RIDE 和真实 Request Throttling，模型替换为 CPU-only Mock vLLM。自动验证启动、依赖、幂等、日志、停止隔离、恢复、普通请求与管理进程重启接管，上传 evidence。不会运行外部 PR；两条 workflow 共享串行组且不取消正在验收的任务。

Mock vLLM 明确标记 evidence_type=mock，token 数、容量和 metrics 是合成值，没有模型权重、GPU 分配或真实缓存。本轮云端驱动 gate PASS，accelerator_resources_requested=0。它可证明部署与管理流程，不能证明真实 tokenizer、缓存行为、调度压力、公平性或性能。当前 fixture 显式拒绝流式请求，流式专项尚待实现。

`.github/workflows/hardware.yml` 仅手动触发，在同一 9450 runner 上对自有真实模型实例运行相同的验收，主动停止/恢复 Controller、重启 RIDE 管理 Job。不停止真实模型，不重启集群，不自动跑性能。测试期间保留原始日志，失败也上传，FAIL/NOT_RUN 不算通过。

runner 标签：self-hosted / linux / ARM64 / ride-9450。当前专用 workspace 为 admin/ride-e2e-myc。runner 和服务随工作区存活；离线时 Actions 会排队，不能宣称一直在线。部署清单是私有云端文件 /workspace/home/ride-platform-v02-20261010/ci-deployment.json，显式列出自有管理 Job、模型/Controller 和地址。工作区重建时必须重新核对并生成此清单，不能沿用旧 head。

Workflow 测试代码以提交版本固定，并复制到不可覆盖的云端源码目录；RIDE 管理服务报告 build_revision。不能对当前旧服务跑几项检查就声称新提交通过。每次 CPU 流程使用独立测试实例和 state，结束只清理自己创建的 Job；真实模型与已有产品实例不参与清理。

公开仓库自托管 runner 只执行 main；不要改为 pull_request_target 或给外部 PR 此 runner 的执行能力。Actions token 仅 contents:read。真实硬件验收由显式 workflow_dispatch 授权执行。脚本、结果与 GitHub workflow 是否成功分别报告；驱动 PASS 不冒充 Actions run PASS。
