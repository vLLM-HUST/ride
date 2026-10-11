> 当前统一开发契约：[RIDE 开发与变更契约](DEVELOPMENT_CONTRACT.md)。旧文中“新建集群”必须通过 Coder admin 标准 RayCluster 工作区；不得直接创建 Kubernetes RayCluster。用户已授权按契约继续；门禁实现与验收状态须分别记录。

# 一键部署和验收入口

在云上安装 RIDE、Demo 和 Request Throttling 后，在同一个既有 Ray 集群中执行：

```bash
./scripts/one-click.sh deploy plan.json results/deployment
./scripts/one-click.sh accept plan.json results/acceptance
```

不创建 Coder template、workspace、网关或 PVC。不启动本地服务或端口转发。
`plan.json` 是验收执行计划，不改变日常 Controller 按名称启动的 CLI 规范。

计划字段：`ray_address`（既有 Ray Jobs URL）、`address`（RIDE API URL）、
`listen`、`management_job_id`（本轮唯一名称）、`config`（云上绝对配置路径）、
`runtime_env`（固定安装包和环境）、`timeout`（秒）、`acceptance_targets`。
每个 target 包含 `controller`、`model_service`、`model`。
配置中的所有实例必须 `autostart=false`。入口提交管理进程，通过 RIDE API 依次启动模型、
等待 Ready、启动 Controller、等待 Ready。管理进程提交前保存意图；已有提交记录时拒绝盲目重复提交。

验收保存每个 Controller 的原始报告、部署/验收动作记录和 SHA256 清单。
部署错误或窄项验收失败退出非零；当前验收入口只执行部署、请求、停止隔离和恢复，
完成后退出 3，明确 `INCOMPLETE`。管理进程重启接管、特定 Controller 的异常请求、
来源和程序语义、性能门禁尚待接入，不能据此宣称完整验收。

当前状态：入口已实现；9450 云上语法检查通过；完整真实模型执行尚未完成。

## 提交前的实时身份门禁

计划必须提供 `deployment_identity`：`coder_url`、`owner`、`workspace_id`、
`template`、`cluster`、`namespace`。云上执行环境提供 `CODER_SESSION_TOKEN` 和
只读 Kubernetes 查询权限；凭据不得写入计划或证据。缺少凭据不得绕过门禁。
入口在任何 Ray 提交前实时查询 Coder 与 Kubernetes，验证登录账号、owner、模板、
工作区 build、标准模板命名的集群、head 的工作区标签及 owner UID、Ready 和 Ray 地址。
Ray URL 只接受关联 head IP，或在该 head 内执行时的 localhost。其他代理形式尚未支持。
`deployment_identity.py` 的九项正反例已在 9450 执行通过，属于 CPU 门禁测试；
真实模型和完整端到端验收尚未完成。
