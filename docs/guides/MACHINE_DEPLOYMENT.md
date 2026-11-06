# 从指定机器部署完整 RIDE 服务

状态：2026-11-06 开发中，尚未完成双 devbox / NPU 验收。入口的 PASS
只表示部署就绪检查通过，不证明真实推理、Controller 动作或性能收益。
本功能在 RIDE 实现；gennova-d 后续消费，不复制部署器。

## 用户入口与责任

安装本分支的 `ride-control-plane[ray]` 后，在可访问目标机器及服务地址的操作环境执行：

```bash
bash scripts/one-click.sh machines-validate deployment.json .ride/deployment
bash scripts/one-click.sh machines-up deployment.json .ride/deployment
bash scripts/one-click.sh machines-status deployment.json .ride/deployment
```

等价的已安装入口是 `python -m ride.deployment validate|up|status|stop PLAN DIRECTORY`。
validate 仅检查配置，无 SSH、安装或远端 Job。up 串行执行：
Ray 官方集群启动器（可选）→ 托管 RIDE 管理 Job → 模型启动/就绪 → 独立 Controller
启动/就绪。操作命令退出后，服务仍是独立 Ray Jobs。

部署前用户或平台提供已授权的机器、设备权限、互通网络、持久目录及模型权重。
bootstrap 的 Ray launcher setup_commands 可以安装明确版本依赖；本入口不安装
宿主驱动、不下载猜测的权重、不更改 Coder 模板或使用宿主 Docker socket。
在 Coder 里先核实 owner、工作区 ID、Pod/设备与实际机器身份；名字不是归属证据。

## 配置契约

以下为结构示例，地址、资源、类型和路径必须按实际环境填写，不能直接作为实机计划：

```json
{
  "schema": "ride.deployment/v1",
  "name": "myc-ride-devbox",
  "ray": {"mode": "existing", "address": "http://10.0.0.10:8265"},
  "management": {
    "endpoint": "http://10.0.0.10:19100", "listen": "0.0.0.0:19100",
    "state_file": "/workspace/home/myc-ride-devbox/state.json",
    "resources": {"node:10.0.0.10": 0.001}, "runtime_env": {}
  },
  "model_services": [{
    "id": "model-a", "type": "vllm", "model": "/models/example",
    "endpoint": "http://10.0.0.11:8000", "port": 8000,
    "num_cpus": 2, "num_gpus": 0,
    "resources": {"NPU": 1, "node:10.0.0.11": 0.001},
    "args": ["--tensor-parallel-size", "1"], "runtime_env": {}
  }],
  "controllers": [{
    "id": "throttle-a", "type": "request-throttling",
    "model_service": "model-a", "backend": "http://10.0.0.11:8000",
    "endpoint": "http://10.0.0.10:9000", "port": 9000,
    "resources": {"node:10.0.0.10": 0.001}, "num_gpus": 0
  }],
  "readiness_timeout_seconds": 600
}
```

Controller spec 原样交给已安装插件；独立请求 Controller 的配置应以该包当前契约为准。
上例内置类型沿现有兼容入口；不能据此声称已验收新版独立包。
各节点安装固定 RIDE/Controller/引擎版本，或在相应 runtime_env 配置固定依赖。
管理 Job 的 working_dir 由入口上传冻结配置；模型和 Controller 使用各自 runtime_env。
管理 Job 必须固定节点，state_file 的父目录在该节点上预先存在且可持久写入。
readiness_timeout_seconds 只控制运维就绪等待，不是推理业务 timeout。

对于新版独立请求包，使用其 `request-throttling-managed` 类型，并在 spec 指定
`configuration`（所有执行节点及管理节点上相同的绝对路径）和
`configuration_sha256`。按请求包的 `ride.controller/v1` 配置声明允许的模型池。
固定副本部署还需声明模型池激活，例如 plan 顶层增加：

```json
{"model_bindings": [{"controller": "throttle-a", "model_services": ["model-a"],
                      "token_env": "RIDE_CONTROLLER_TOKEN"}]}
```

入口先检查操作环境的 token 变量存在，再启动服务；全部服务就绪后，通过公开
`/control/capabilities` 协商预声明模型池能力，并调用 `/control/activate`。
只激活本次已启动、Ready 且 Job ID 精确匹配的模型，核对 activated/replica/job_id
回执；UNKNOWN 不自动重放。token 值不写进命令行；Controller 环境需使用同一凭据。
这只连接用户明确指定的固定模型池，不实现调度算法或扩缩决策。
固定副本模式的模型由部署器拥有；不能再启动另一个实例 Controller 接管同一批模型。

bootstrap 模式将 ray 改为：

```json
{"mode": "bootstrap", "address": "http://10.0.0.10:8265",
 "cluster_config": "/absolute/path/cluster.json"}
```

cluster.json 使用 Ray 官方 local provider 配置（JSON 同时是合法 YAML）；明确
cluster_name（等于部署 name）、provider.head_ip、provider.worker_ips、auth、
file_mounts、setup_commands 和 Ray 启动命令。配置及依赖需固定，不从浮动 main 安装。
入口调用 `ray up -y --no-restart /absolute/path/cluster.json`，记录配置 SHA。
仅用于本次专用、已确认无冲突的机器；--no-restart 不是多租户归属门禁。

复用官方启动器：[Ray on-premise deployment](https://docs.ray.io/en/latest/cluster/vms/user-guides/launching-clusters/on-premises.html)。
Coder 的 SSH 代理、rsync、节点内部地址及工作区间连通性必须实际验证，不能因
Coder terminal 可用就推断官方 launcher 可用。不适配时先修本入口，不用手工启动冒充一键成功。

## 身份、重复执行和失败

操作目录保存 SQLite Journal、管理配置和 readiness.json。配置与集群文件 SHA
固定；同目录换配置拒绝。每次远端动作前持久记录 intent；完成动作重用回执。
启动结果未知时保留 UNKNOWN，下一次拒绝盲重试。应检查原 Job、操作接口和日志，
当前版本尚未提供自动确认 UNKNOWN 的恢复命令，不能删 Journal 来重投。
模型就绪失败可重新执行同配置 up，仅继续检查已有 Job，不重复启动。
模型与 Controller 由公开 SDK 条件启动；已有同名的其他 Job 不被静默接管。
管理地址的 workspace/name、管理 Job entrypoint/metadata 和服务 Job ID 均核验。
就绪失败不自动全量回滚，保留日志和已有服务，以免破坏仍在执行的工作。

显式停止（会中止运行中的请求，不等于排空）：

```bash
bash scripts/one-click.sh machines-stop deployment.json .ride/deployment
```

仅按记录依次停止 Controller、模型、管理 Job；不运行 ray down/ray stop，
不删除 devbox/卷/共享权重。正常在线缩容仍应使用实例 Controller 的请求/KV 排空契约。
停止后需核终态；停止中的部署不允许 up 自动重建。管理状态和部署 Journal 均保留。

## 分阶段验收

1. 软件：顺序、配置冲突、就绪阻断、重复部署、未知提交、准确停止和安装入口。
2. 单 devbox：真实 Ray 管理/模型/Controller Job，命令退出后继续服务。
3. 双 devbox：两个 TP1 模型，地址与设备身份正确，真实请求和限流动作。
4. 异常/接管：重复 up、部分启动失败、管理进程重启接管、停止隔离、归档/回收。
5. 后续：单模型跨机器 TP/PP 与性能分别验收，不由双 TP1 推出。

首轮固定两个已分配 devbox、至多两张 NPU；具体平台、工作区、物理设备、源码、
镜像、模型和运维收尾时间须在真实执行前冻结。无有效身份/网络/设备证据不提交模型。
