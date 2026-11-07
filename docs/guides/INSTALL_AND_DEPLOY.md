> 当前部署边界：[复用已有 RayCluster](../reference/DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

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

## 管理服务重启接管的独立验收

```sh
scripts/one-click.sh accept-adoption /absolute/frozen-plan.json /absolute/new-evidence-directory
```

计划保留原部署的`address`、`ray_address`、`management_job_id`、`runtime_env`和平台身份，`deployment_output`指向含`management-submission.json`的原部署证据目录。可显式冻结`adoption_job_id`，值必须将原管理 Submission ID 的 `execution-N` 递增为 `execution-(N+1)`；组件显示名仍为 `RIDE Control Plane`。`timeout`是运维就绪检查期限，不是业务请求timeout。

入口先核平台与Ray关联、原管理Job为RUNNING且命令匹配、现存运行实例Ready。已存在停止或接管意图则拒绝重投。随后仅替换管理Job，读取原状态目录，要求run_id相同、管理进程改变、所有Controller和模型Job ID不变。原本STOPPED的模型保持STOPPED；运行中的实例等待恢复Ready。执行绑定改为新管理Job，冻结输入文件不改写。

这项PASS只说明管理接管，不说明模型提交、限流层运行态恢复或性能。控制器必须自行处理只读观测暂时失败；不能忽略其错误来取得通过。限流层仅允许已释放全部任务、无在途和未知请求的空状态重启；非空Router恢复仍不支持。

故障注入可在冻结计划声明`management_restart_delay_seconds`，默认0，范围0–30秒；用于明确观测停止与重启之间的窗口，计入运维耗时，不作为策略收益。

## 文件传输中断的边界

`scripts/deployment_payload.py`提供`initialize_staging(destination, identity)`和`stage_archive(archive, destination, identity, expected_sha256)`，供部署操作方在提交任何Job前准备源码。identity明确绑定run、workspace和冻结plan SHA；目录必须私有、非符号链接，未知已有目录和身份冲突拒绝，不凭目录名推断平台归属。平台owner、Pod UID和RayCluster关系仍由既有身份门禁核验。

同一归档可补齐缺失文件，已有相同文件保留，任何内容、模式、归档身份或路径冲突都在写入前拒绝。完整临时文件以排他方式发布，避免留下半个最终文件；原子写入中断后可重新核验同一归档。随后仍调用既有`prepare_payload`，核精确Pod/cluster身份、逐文件SHA和目标读回。

这只适用于冻结文件阶段，既不启动服务，也不重试模型或业务提交。SSH失败先保存原失败并查原目录/归档/回执，确认相同身份和SHA后才继续文件阶段；未知Job仍按原Job ID查账。文件阶段成功也不代表实际镜像、Controller功能或性能通过。r38在该阶段失败且0模型/0业务，历史记录保留。r39在写入前拒绝了实际归档中权限0666的空uv安装锁；构包排除该临时文件后，r40相同归档两次云端准备和两Pod逐文件读回通过，随后完成独立Controller与真实模型匹配批次。尚未在真实传输中断后验证全部补齐分支；该负例目前由软件回归覆盖，不称SSH根因修复。


### 配置工作区存储根

`plan.payload.workspace_root`显式声明目标Pod中的工作区目录，`destination`必须是它的严格子目录。例如存储根可以是`/mnt/inference`、`/home/serving`或平台提供的持久卷挂载；迁移只改配置，不替换部署源码。旧计划未提供此字段时保留`/workspace/home`作为兼容默认，新环境应显式填写。该字段不证明平台所有权或持久性；仍须核实际workspace/Pod/cluster身份及挂载。拒绝根文件系统、相对路径、越界、符号链接和已有内容冲突；逐文件SHA、模式、排他发布和读回验证保持。测试使用同一未修改远端代码覆盖不同存储根。
