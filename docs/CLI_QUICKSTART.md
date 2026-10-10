# 将 Controller 部署到已有 Ray 集群

RIDE 是控制平面，Request Throttling 是 Controller，Ray 执行独立进程。
目标只有三步：连接已有 Ray、部署 Controller、查询运行结果。Web UI 不参与前置验收。

## 1. 准备运行环境

在云端工作区安装 RIDE：

```sh
python -m pip install '.[ray]'
```

Ray 节点需要安装 Request Throttling Controller 及它固定版本的上游依赖。
RIDE 不会自动安装 Controller；它通过 Ray Jobs 的 runtime_env 使用节点环境。
当前 Controller 来源为 vLLM-HUST/request-throttling-controller，验收版本
cb4c4e5c46875ea7f2a0a8618c54c9bb39989926；上游 ThunderAgent 固定
7ddc8610270e56d3b109eed8796b3a4360fc67c9。
私有仓库需要已有读取权限。安装可使用 Controller 仓库提供的 `.[upstream]`。
多节点应在所有可能执行该进程的节点安装，或通过 `--runtime-env` 提供相同环境。

## 2. 连接已有 Ray 并部署

在工作区一个终端启动 RIDE 管理进程，保持终端运行：

```sh
ride start --ray-address http://RAY_HEAD:8265 \
  --workspace YOUR_WORKSPACE --state-file /persistent/path/ride-state.json
```

8265 是 Ray Jobs HTTP 地址。这里不启动或重启已有 Ray。
管理进程默认监听工作区内 127.0.0.1:19100；以下命令在同一工作区另一个终端执行。

```sh
ride start controller request-throttling --name throttle-main \
  --backend http://VLLM_HOST:8000 \
  --endpoint http://CONTROLLER_HOST:9011 --port 9011 \
  --num-cpus 0.1 --num-gpus 0 --transport no-keepalive

ride get controller
ride describe controller throttle-main
ride logs controller throttle-main
```

backend 是已有 vLLM 的地址；endpoint 是 Controller 进程对外可达的地址。
Ray 多节点时需用 `--resources` 将进程放到对应节点，或按实际部署提供可达入口；
RIDE 当前不会自动分配服务入口、负载均衡或端口。
`job_status=RUNNING` 且 `ready=true` 表示 Ray 进程正在运行、Controller 及后端健康检查通过。
客户端将模型请求发往 Controller 的 endpoint，而不是 RIDE 管理端口。

停止、恢复只针对该实例：

```sh
ride stop controller throttle-main
ride start controller throttle-main
```

停止不会停止 vLLM；恢复使用保留的实例配置。停止并非 graceful drain。

## 3. 9450 CPU 验收记录

工作区 admin/ride-cpu-ui-myc，使用真实 Ray 2.48.0、RIDE 0.2.0 和 Controller，
模型后端为 mock-vllm，无加速卡申请。Controller 首次提交 Job ID：
`ride-controller-a263f4e081c94aa99b264fd7a37ae305-fea96a42`。
实测 `job_status=RUNNING`、`ready=true`，实际 Router 为
`ThunderAgent.scheduler.router.MultiBackendRouter`。

标准验收命令：

```sh
ride verify --controller request-throttling --model-service mock-model \
  --model mock-vllm --lifecycle --output cli-acceptance.json
```

原始结果保存在 results/9450-cli-delivery/。CPU Mock 只验证部署、生命周期与请求链路；
不验证 GPU/NPU、缓存、真实模型性能或 Web UI。
临时工作区不是长期运行入口；实例地址和 Job ID 不能作为后续部署的固定配置。
