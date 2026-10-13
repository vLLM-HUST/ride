# Request Throttling 与 Demo 重新验收计划

状态：PLAN / 用户已明确授权新建一个共用 RayCluster。日期：2026-10-11。旧验收不计入本轮通过。
用户目标是可检查的真实 NPU 端到端交付；本轮必须先发布动作与预期，再执行。

## 1. 目标、责任与环境锁定

用户在 2026-10-11 明确授权本轮新建一个共用 RayCluster；直接创建 RayCluster，
不创建 Coder template/workspace、网关或持久卷。两个 Controller 和模型共用此集群，后续只管理 Jobs。模型、两个 Controller 和验收客户端使用独立、可读的 Ray Job 名称。
RIDE 管理它们的提交、状态、日志、停止和恢复；Controller 执行业务控制。
仅清理本轮记录的 Jobs，不重启或删除复用的平台。

2026-10-11 只读 `kubectl get rayclusters -A -o json` 返回 items=[]。
这是 Kubernetes 对象查询结果，不证明所有 devbox 中没有手动 Ray。
用户随后明确授权新建集群，环境名 ride-reacceptance-myc-20261011。
这是对本轮集群创建的具体授权，不改变不得按 Controller 创建模板/工作区的规则。

执行前生成 manifest.json：run_id、开始时间、Ray 地址、节点与设备归属、模型文件及哈希、
vLLM/CANN/驱动版本、RIDE/Controller/Demo/官方提交、dirty、实际加载源码、环境变量白名单、
完整命令、资源、Job IDs、输出路径。实际版本取运行环境，不凭本地版本推断。
提交的源码或依赖发生变更则新建 run，不热改运行任务。

## 2. 验收动作与预期

| ID | 动作 | 预期与通过标准 | 原始证据 |
|---|---|---|---|
| E01 | 查询指定 Ray API、节点、资源和本轮允许使用的 NPU | 地址可达；资源与设备权限一致；无冒用他人设备 | environment.json、devices.txt、jobs-before.json |
| E02 | 从固定源码安装 RIDE 与两个 Controller，在实际节点检查 import 路径与版本 | 适配器可发现；来源与锁定版本一致；无旧目录隐式依赖 | install.log、source-manifest.json、loaded-identity.json |
| E03 | 运行 deploy.sh 连接已有 Ray | RIDE 管理 API 可用；集群/平台对象数量未增加；未重启已有 Ray | deploy.log、platform-before/after.json |
| E04 | 用 RIDE 提交真实 NPU vLLM；客户端直接请求模型 | RUNNING 且 Ready；NPU 进程属于本 Job；非空输出，真实 prompt/completion tokens | model.log、model-identity.json、direct-responses.json、devices-running.txt |
| D01 | 用 ride start controller demo 部署并发限制 1 | 实际身份 demo，后端正确；Ready；非 Mock | demo-start.log、demo-identity.json |
| D02 | 同时发送 4 个真实非流式请求，采样 active/waiting | 4/4 成功，failed=0，peak_active=1，queued_total>=1；结束 active=waiting=0 | demo-requests.jsonl、demo-state-timeseries.jsonl |
| D03 | 同输入 temperature=0 直接模型与 Demo 对照 | 响应结构、token 用量、输出内容一致；如有差异原样保存并 FAIL/定位，不改判据 | demo-direct-comparison.json |
| D04 | 错误请求与流式请求，再正常请求 | 不支持的请求明确拒绝；正常请求仍成功；无永久占用并发槽 | demo-negative.json |
| T01 | 用 RIDE 部署 Request Throttling 默认产品入口 | 实际 MultiBackendRouter、固定官方来源哈希、有效 backend/enable/transport 均正确 | controller.log、migration-identity.json、source-diff.json |
| T02 | 两个 program 各三轮真实请求，记录输入历史/token/hash | 六步零错；历史累积正确；普通无身份请求不创建 Program | program-requests.jsonl、history-audit.json、program-state-timeseries.jsonl |
| T03 | 在明确压力配置下展示进入、暂停、恢复、完成与释放；官方原版同输入对照 | 每个状态有实际状态/日志证据；释放后无残留；官方与产品语义匹配；未触发不能 PASS | lifecycle-events.json、upstream-state-comparison.json |
| L01 | 对两个 Controller 分别重复 start | RUNNING 实例 Job ID 不变；配置冲突明确拒绝 | idempotence.json |
| L02 | 分别 stop Controller，再直接请求模型 | 本 Controller 到终态；模型相同 Job ID 且 Ready、推理成功；另一 Controller 不受影响 | isolation.json、jobs-during.json |
| L03 | 恢复两个 Controller 并请求 | 新 Job ID、Ready、真实推理成功 | restore.json |
| L04 | 只重启本轮 RIDE 管理进程，保留 state_file | run_id 和既有模型/Controller Jobs 不变；状态及推理恢复 | adoption.json、before/after-state.json |
| C01 | 导出日志、结果、哈希，再停止本轮 Jobs | 结果可读；本轮 Jobs 终态；复用集群仍正常、他人 Jobs 不变 | artifact-sha256.json、cleanup.json、jobs-after.json |

每个动作记录 exact_command、started_at、finished_at、exit_code、expected、observed、status、
evidence_paths。允许 PASS/FAIL/BLOCKED/NOT_RUN，缺失证据不算 PASS。
CLI 查询本身不证明控制动作；Controller 自报计数必须结合客户端响应、采样和后端日志交叉核对。

## 3. 性能验收与效力边界

先通过 E、D、T、L 正确性，再执行 Request Throttling 性能验收。
同一模型、设备、输入、历史、配置，在同轮依次测 direct vLLM、固定官方 ThunderAgent、
RIDE 部署的 Request Throttling。并发指 program/workflow 数量，不是卡数。
初步点 8/32/128；每种 1200 秒，统计 400–1200 秒；三次重复，取中位数并保留每次值。
零请求错误、零历史/token 偏差为有效性前置门禁；产品吞吐至少官方 90%，且在高压点超过
同轮基线，才支持该点性能交付。若真实硬件容量不适用这些点，先写明新预注册计划，再运行。

低并发重合、基线峰后下降、Controller 高压保持、缓存/队列证据逐项核对；
未出现就报告未复现，不调参数凑结论，不称完整论文 Figure1a 复现。
Demo 的并发限制属于功能控制，不要求提高吞吐；不得把串行排队称为性能收益。
窗口截断的 completed-program 延迟不能冒充全部 program E2E；完整 E2E 延迟需固定集合 drain。

性能产物统一 comparison.csv、time-series.csv，再生成 PNG/PDF并查看；原始与归一化口径分开。
真实 Qwen 小模型 smoke 不证明大模型性能，单次成功不证明长期稳定或公平性。

## 4. 执行顺序、报告与失败处理

阶段一：计划飞书发布读回 → 确认已有 Ray 地址 → 锁定 manifest。
阶段二：安装/部署 → NPU模型 → Demo 控制与负例 → Request Throttling 来源与语义。
阶段三：幂等/隔离/恢复/管理重启 → 正确性报告。
阶段四：性能对照与图 → 日志归档 → owned Jobs 清理 → 最终飞书报告。

任一失败：先保存服务与客户端原始日志，标出失败 ID、原因与影响；修复代码并测试，
固定新提交后新 run 重验相关及回归项。不能只改文档成 PASS。
预计耗时仅在知道设备、模型和环境后给出；性能原始测量时间约 9 小时（3点×3策略×3次×1200秒），
不把该时间承诺成完成时间。环境未确定时没有可靠 ETA。

飞书同一 RIDE 设计文档增量记录计划、实际动作账本、证据与结论；不覆盖历史。
本地完整原始证据目录：ride/results/reacceptance-20261011/<run_id>/。
公开摘要去除凭据和内部地址，原始证据保存供用户核查。
