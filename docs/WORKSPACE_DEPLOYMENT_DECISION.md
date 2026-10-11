> 当前部署边界：[复用已有 RayCluster](DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

> 本文涉及旧环境、旧入口或临时资源的内容为历史记录／早期规划，不是当前部署操作指南。已删除资源不得据此重建。

# RIDE 部署与交付决策记录

日期：2026-10-10。来源：用户明确纠正和要求记录。

## 已确定

1. 品牌为 RIDE，入口为 `ride`；框架独立仓库，controller 保留独立实现仓库。
2. 每个 Coder workspace 独立运行自己的 RIDE、controller、配置和日志。Coder 提供工作区、认证和应用代理。
3. 用户在 workspace 内运行 `ride serve --controller ...`，从该 workspace 的 RIDE Coder App 打开 UI。命令是目标接口，当前原型尚未实现 controller 启动。
4. Ray 工作区也在本工作区运行 RIDE，由本工作区 Coder Agent 代理应用端口；不使用临时 Pod 地址或把 Ray Dashboard 当 RIDE。
5. 性能第一，统一接入契约不强迫算法重写，也不强迫所有请求经过管理 API。
6. 页面展示真实 controller、有效配置、引擎连接、队列、吞吐和操作记录。空页面和原始 JSON 不能算产品交付。
7. 验收包含 workspace 中真实启动、浏览器访问、UI/API/实际运行一致、权限、停止与恢复，以及新旧入口性能回归。

## 已撤销的错误部署

此前宿主机共享 RIDE 服务与平台 `/ride/` 路径不符合目标，已停用服务并移除两处新增网关 location。nginx -t 通过，Coder /healthz=200。旧验收文档保留作废标记，不再作为 workspace 验收依据。

## 仍待实现

Controller 生命周期接入、workspace Coder App 发布、真实 Ray 应用部署、有效管理 UI 及端到端验收。当前不能宣称 RIDE 框架或平台已完成。开发不得热改正在运行的 9443 性能实验。
