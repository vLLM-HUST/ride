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

## 补充真实策略验收（2026-10-11）

工作区内 RIDE 只访问 Ray；Coder/Kubernetes 身份核验在已有云上运维入口执行，
不授予工作区查询 RayCluster 的权限。`cloud_operator.py` 只传输执行请求，
不在本地启动服务或端口。平台预先提供 admin 标准 RayCluster 工作区。

部署及功能验收完成后，使用同一入口补充缺失项目：

```bash
python3 scripts/cloud_operator.py accept-policy \
  --ssh-host <existing-cloud-operator-host> \
  --cloud-root <cloud-evidence-root> \
  --coder-url <coder-url> --plan plan-policy.json \
  --output <unique-run>/policy
```

计划必须引用已有功能验收账本（所有动作 PASS），明确压力模型与 controller 实例、
依赖、Ray 节点资源及真实模型参数。补充入口仍通过 RIDE API 部署进程，
不创建平台资源，也不重启已运行服务。运行中的产品包不改动。

压力场景：32 个 program，真实模型 KV 固定 64×128=8192 token；通过 `state=paused` 观察实际暂停状态（`status` 表示 reasoning/acting 阶段），
释放已完成 program 后，同一个等待中的暂停 program 必须恢复并完成首轮，
其下一轮也必须正常完成，
历史 tokenize 数量一致，最后释放所有 program。180 秒阶段超时即 FAIL。
保留逐次状态、输入输出、Ray 日志、账本与哈希。

同输入短对照：direct、Demo、Request Throttling，普通无身份请求，
并发 1/4/8，每点两轮交替顺序，64 输出 token，temperature=0。
所有响应的内容与 token 数哈希一致；原始耗时与 requests/s 写入统一 CSV。
此对照不测试 program-aware 调度收益，不是 Figure1a 或正式性能复现，
不使用短测结果替代三方 program 性能门禁。

本阶段 PASS 只证明 RIDE 真实 NPU 部署、功能、生命周期及有界压力控制；
上游完整语义对照与研究性能验收仍按独立契约判断。
# 跨节点实验数据与结果

工作区挂载 `/workspace/home` 不表示不同节点共享同一份数据。
部署计划必须记录 payload 的来源、SHA256、实际执行节点以及数据路径。
在提交服务前，于实际执行 Pod 验证模型、数据、配置和 Python 依赖可读；
不得只在控制节点检查路径，然后假定 Ray worker 可见。

跨节点有两种明确选择：共享存储，或将固定 payload 显式搬入已授权 Pod。
不得改建模板、创建新工作区或改变平台存储来绕过应用部署缺口。
手工搬移只有在记录精确 Pod UID、文件 hash 和结果时才是可追溯证据，
仍不能称部署入口已自动完成该步骤。

Request Throttling 的标准结果回收、归档和旧绘图入口：

```bash
make ride-report PYTHON=<cloud-python> RUN=<collected-run> RESULTS=<new-report-directory> \
  ARGS="--pod-source <identity-json>"
```

identity-json 必须含 namespace、cluster、cluster_uid、pod、pod_uid、remote_run。
回收是只读应用证据操作，不管理工作区生命周期。
有限集合报告使用完整 makespan/program E2E，固定窗口报告使用预注册测量窗口；
两者不能混用。raw 原始归档保留 SHA256，图和报告是可重新生成的派生物。

deploy计划可包含以下可选字段；source和目标均必须在冻结计划中明确：

```json
{
  "payload": {
    "namespace": "coder-workspaces",
    "cluster": "<owned-existing-raycluster>",
    "cluster_uid": "<observed-uid>",
    "pod": "<owned-execution-pod>",
    "pod_uid": "<observed-pod-uid>",
    "destination": "/workspace/home/<run>/payload",
    "files": [
      {"source": "/cloud/control-node/<run>/config.json", "path": "config.json", "sha256": "<frozen-file-sha256>"}
    ]
  }
}
```

入口在原有部署身份检查后、服务提交前准备payload。
校验Pod属于指定RayCluster，源hash与计划一致，远端内容逐文件读回一致；
已有不同文件拒绝覆盖，符号链接或越界路径拒绝，256MiB以上用共享存储。
控制节点有该目标namespace读取和Pod exec权限才可选此步骤；
不能让普通工作区ServiceAccount去查询全平台或扩权限绕过403。
仅将文件准备到计划指定Pod，不会自动给其他Ray节点复制。
使用本地路径的服务必须显式固定到该节点，或由共享存储保证可读。

真实实验已验证数据搬移前置检查；统一报告与身份回收已验证。
deploy可选payload已实现并通过云CPU合约检查，完整实际Pod部署组合待验收。
