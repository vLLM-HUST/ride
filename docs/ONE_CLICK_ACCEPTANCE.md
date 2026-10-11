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
