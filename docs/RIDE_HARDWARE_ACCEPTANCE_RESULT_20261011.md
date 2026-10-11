# RIDE 真实 NPU 部署与控制验收结果

2026-10-11：RIDE 的真实 NPU 部署、两种 Controller 功能和生命周期、有界压力验收通过。
这不是 ThunderAgent 完整迁移性能或 Figure1a 复现结论。

## 环境与执行

9450，Coder admin，标准 ascend-raycluster 工作区 ride-shared-myc。
RIDE 管理同一 Ray 集群内的真实 Qwen3-0.6B vLLM、Demo、Request Throttling 独立 Job。
平台身份检查由已有云上运维入口完成；工作区不需要查询 Kubernetes RayCluster。
源码：RIDE 07a3c9f；Demo 717458c；Controller cb4c4e5；官方 ThunderAgent 7ddc861。
压力服务实际加载17个官方源文件哈希一致，实际后端及 scheduling_enabled核查通过。
Controller 传输显式 no-keepalive，timeout900，无新增重试。

## 门禁与真实结果

|项目|结果|证据|
|---|---|---|
|真实模型、两个 Controller 经 RIDE 部署到 Ray|PASS|deployment 账本、Ray日志|
|Demo 实际单并发、排队、负例后释放槽位|PASS|acceptance-2/accept.json|
|多轮历史/token、进入reasoning、完成acting、释放|PASS|acceptance-2/accept.json|
|幂等、停止隔离、恢复、RIDE重启接管原Job|PASS|acceptance-2/accept.json|
|容量压力下等待Program暂停、释放容量后恢复、两轮完成及最终释放|PASS|policy-2/pressure-result.json|
|三条路径同输入输出及token哈希|PASS|policy-2/comparison-responses.json|
|完整Program性能收益、官方性能差距、Figure1a|NOT_RUN|本轮短测不覆盖|

压力模型独立占用同一工作区第二张 NPU；真实 KV64×128=8192token，32个Program。
实际暂停Program为pressure-program-10。释放其他完成Program后首轮恢复，第二轮step_count=2，
status=acting、state=active，最终32个Program全部释放且无状态残留。
本场景证明等待队列暂停/恢复，不证明中断正在执行的模型解码。

短测使用普通无Program身份请求：64输出token，temperature0，每并发点两轮，交替顺序。
78个请求全部输出内容与token哈希一致。均值如下，单位requests/s：

|并发请求|直接vLLM|Demo（max_concurrency=1）|Request Throttling|
|---|---:|---:|---:|
|1|0.2380|0.2361|0.2371|
|4|0.8739|0.2396|0.8769|
|8|1.7352|0.2427|1.7814|

Request Throttling普通旁路与直接vLLM接近，Demo串行吞吐符合设定。
这些短测差异不构成调度性能收益；没有使用历史192program数字。

## 失败、修正与复现

policy-1保留FAIL：验收脚本把status阶段与state生命周期混淆，并要求已完成Program暂停，
漏掉实际等待队列的state=paused。修正的是验收观察，未修改官方策略。
policy-2使用新实例身份，旧失败及各服务日志归档后只停止旧压力Controller。
原模型、Demo及主Request Throttling未停止；集群未重启，未新增工作区或模板。

统一入口：scripts/one-click.sh deploy|accept|accept-policy。
用法与固定判据见[ONE_CLICK_ACCEPTANCE](ONE_CLICK_ACCEPTANCE.md)。
云上证据根目录：/data/users/admin/ride-reacceptance-20261011/run-20261011c/。
本地仅回收证据：results/reacceptance-20261011/policy-2/，包含CSV、响应、状态、各Ray日志和SHA256。
部署账本、功能账本和补充账本共同组成此次RIDE有界验收；不得把单一PASS升级为完整上游语义/性能证明。
