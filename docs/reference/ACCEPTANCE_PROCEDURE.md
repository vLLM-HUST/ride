# 验收执行规范：计划、动作账本、证据与结论

本规范约束所有 coding agent。依据现有 ride.acceptance/v1、Demo npu_acceptance.py、
上游迁移来源/语义/性能门禁及重新验收计划制定。它是执行规程，不宣称现有脚本自动覆盖全部门禁。

## 1. 执行前：冻结验收契约

必须先阅读 AGENTS.md、DEPLOYMENT_POLICY.md、被测 Controller 的实现与验收脚本。
先提交计划，再运行实验。使用 acceptance/plan-template.json，填入：
目标、被测版本、平台范围与授权依据、环境、各动作、预期、机器可判定标准、证据路径、
失败处理、清理对象和结论边界。占位符未填完则状态 BLOCKED，不可开始有副作用的动作。
用户要求飞书时，计划发布并读回后才执行。

环境默认已有 RayCluster。用户明确授权新建一个共用 RayCluster时，只创建该集群，
不推导为创建 Coder template/workspace/PVC/网关的授权。具体授权写入 platform_authorization。
环境不足时报告实测缺口；不得擅自扩大资源范围。禁止把旧地址、旧 Job、旧结果混入新 run。

## 2. 执行中：每项动作都有预期和实际结果

每项保留动作 ID、exact_command、started_at、finished_at、exit_code、expected、observed、
status、evidence_paths、artifacts_sha256。复杂命令保存在命令文件中，不只记录口头摘要。
PASS 要求所有对应判据成立，证据文件非空且可读。状态只用 PASS/FAIL/BLOCKED/NOT_RUN。
进程提交成功、健康 200、Ray RUNNING、Controller Ready、策略有效分别判断。
不得用健康代替语义，不得用 CPU Mock 代替真实 NPU，不得用“部分通过”称完整验收。

固定阶段：环境/权限 → 来源/版本 → 安装部署 → 真实模型直接请求 → Controller 控制动作与正确性
→ 负例 → 幂等/隔离/恢复 → 管理进程接管 → 性能（若目标包含）→ 归档/清理。
Request Throttling 增加官方源码哈希、actual loaded identity、历史与 token 核对、
进入/暂停/恢复/完成/释放对照。Demo 增加实际并发与排队、后端响应、失败后槽位释放。

所有长等待都有超时和可见状态；状态改变、失败或阻断立即报告。
运行中的任务不热改。源码或有效配置变化时保存旧失败，固定新版本、新 run，重验受影响项。

## 3. 失败与清理

先保存客户端、模型、Controller、Ray 原始日志和状态，记录第一个失败层，再修复。
只允许停止 manifest 中记录且属于本轮的 Jobs。清理前归档并校验哈希，清理后核对终态。
复用的集群、工作区、模板和卷不在默认清理范围；新建的共用集群是否保留按用户具体要求。
未知归属的进程不得操作，不为腾卡停止他人服务。

## 4. 交付判断

最终提供每项门禁表、失败/未执行项、复现命令、源码版本、原始证据及派生图路径、清理清单。
同一数据生成表、CSV与图，不手工改数字。性能使用同输入同硬件同配置的有效基线，
错误或历史偏差使该轮性能 INVALID。smoke 只能证明该最小运行，不称论文性能复现。
旧报告 append 保留，当前汇总指向新 run；不静默覆盖旧失败。

本轮具体动作见 REACCEPTANCE_PLAN_20261011.md。future Controller 按同一结构补自己的判据。
“文档写了规范”不等于“代码自动强制”；现有脚本缺少的负例/接管/账本必须补齐后再验收。
