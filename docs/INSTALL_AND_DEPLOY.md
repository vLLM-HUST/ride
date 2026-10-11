# 安装 RIDE，部署到已有 RayCluster

只复用已有 RayCluster。以下脚本不会创建 Coder template/workspace、Kubernetes 对象，
也不会启动或重启 Ray。RIDE 仅在已有集群中管理自己的 Controller 和模型 Ray Jobs。

## 安装和启动控制平面

在自己的云端工作区或 Ray head 环境中：

```sh
git clone https://github.com/vLLM-HUST/ride.git
cd ride
bash scripts/install.sh /persistent/path/ride-venv
source /persistent/path/ride-venv/bin/activate
bash scripts/deploy.sh http://RAY_HEAD:8265 /persistent/path/ride-state.json my-workspace
```

管理进程保持前台运行，默认监听 127.0.0.1:19100。重启时复用同一 state 文件以恢复
owned Job 记录。跨主机访问需要自行提供受保护入口；不要把无认证管理 API 直接暴露公网。

## 安装 Controller，再用统一命令提交

在管理环境及所有可能执行该 Job 的 Ray 节点安装 Controller；新装适配器后重启管理进程。
也可以通过 Ray runtime_env 提供固定版本依赖。

```sh
python -m pip install 'git+https://github.com/vLLM-HUST/ride-controller-demo.git'
ride start controller demo --name demo-main \
  --backend http://VLLM_HOST:8000 \
  --endpoint http://CONTROLLER_HOST:9012 --port 9012 \
  --num-cpus 0.1 --num-gpus 0
ride describe controller demo-main
ride logs controller demo-main
ride stop controller demo-main
ride start controller demo-main
```

生产或复现运行应将依赖 URL 固定到已审查 commit，而不是浮动 main。
endpoint 必须对应进程实际执行节点。多节点通过 --resources 指定节点资源约束；
当前无自动端口分配、服务发现和负载均衡。backend 是已有真实 vLLM 地址。
Demo 实现非流式请求并发限制，默认上限 1。

如果由 RIDE 启动模型，使用 `ride start model-service vllm`，明确模型路径、资源与运行环境。
GPU 用 --num-gpus；NPU 用实际 Ray 自定义资源（例如 --resources '{"NPU":1}'）。
这只是 Ray 资源声明，设备权限必须由已有集群提供。
Ascend CANN/ATB 的动态库路径必须存在于模型 Job 环境；本次 NPU 验收通过显式
runtime_env 修复 libatb.so 路径。安装 RIDE 不等于配置好硬件运行环境。

## 已有证据与边界

Demo 单张 NPU 真实 vLLM 请求、并发限制、停止和恢复的结果：
[验收摘要](https://github.com/vLLM-HUST/ride-controller-demo/blob/main/results/npu-20261011/summary.json)。
上述两个包装脚本尚未独立云端执行；底层 ride start / Controller / model-service 命令已经云端验收。
脚本不会建立新的集群。CPU 检查不能代替真实 NPU 端到端验收。
