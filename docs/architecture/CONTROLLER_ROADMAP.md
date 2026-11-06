# RIDE 与 Controller 项目统一路线图

项目目标、范围与阶段验收：[中长期规划](../PROJECT_PLAN.md)。系统边界：[统一技术设计](INDEPENDENT_CONTROLLERS.md)。本表是唯一跨仓库任务状态，更新于2026-11-06；软件、云端托管、真模型和收益分别核销。

## 当前研究顺序（2026-11-06用户确认逐项推进）

**唯一活动主线：第一项Instance，当前按3–4天首轮目标推进，第1天为资格及测量准备；已开始离线工作量工具开发与历史核验，尚未提交新资源、模型或性能作业。** 各项问题、基线、周期和出口见[中长期规划第2–4节](../PROJECT_PLAN.md#2-近期每项约三至四天按顺序完成首轮研究)。下面勾选仅代表该项完整出口通过，不用旧软件通过或历史模型功能替代。

- [ ] 前置：新组合真实Ray/模型生命周期；输入/输出工作量核验；单副本容量与启动成本标定。
- [ ] 第一项Instance：成熟工作量感知策略接入，强基线、独立重复、留出、收益/负结果与边界判读。
- [ ] 第二项缓存感知路由：固定副本，隔离真实缓存/负载取舍，完成强基线与效力边界；尚未启动。
- [ ] 第三项KV：单一真实后端状态资格，再测保留/恢复与重算成本；尚未启动新策略。
- [ ] 第四项协同：以实测冲突为前提，比独立组合验证增量及消融；尚未启动。
- [ ] 后续完整控制域：引擎/P-D、模型/LoRA、并行拓扑、工作流/SLO与外部复用按依赖逐项立题；尚未启动。

立即下一份交付物：Instance容量与启动标定、工作量核验及首个匹配发现对照的冻结方案；先核来源/基线与所需观察字段，再按既有授权和资源门禁执行。每周按规划第5节五问复盘；只有本表更新任务状态。

当前设计已收敛为[RFC-0001](../rfcs/0001-instance-autoscaling.md)，状态Draft，待评审；问题、算法、接口、生命周期、验证及未决选择以该文档为单一设计来源。[RFC规范和模板](../rfcs/README.md)供后续独立Controller复用。当前任务先形成可评审设计，本轮未实施RFC的新接口/策略，未启动资源或实验；3–4天目标和历史未完成项保持。

第一项第1天已开始离线测量准备：请求仓新增`experiments/workload/analyze_controller_pair.py`及对应回归，核验原件身份、逐轮真实输出继承和实际工作量。验证原件、历史诊断及本轮软件结果保留在主计划与benchmark证据归档流程，不在控制面仓新增成绩表。当前还未完成新版工具的Coder资格、真实模型容量/启动标定或收益对照；下一步按既有入口完成这些前置，不挪用上一轮软件资格。

## 项目对齐表

| 项目 | 责任 | 本轮实际进度 | 下一项 |
|---|---|---|---|
| ride | 公共SDK、注册发现、模型/Controller生命周期与Ray执行 | SDK0.3.4 7551ee5：统一对象/版本/条件动作与持久回执，90项Mac及实际Coder Linux软件检查通过，新Linux CI通过；[草稿PR #2](https://github.com/vLLM-HUST/ride/pull/2)未合并，组织证据review开放 | 为Instance完成新版真实Ray/NPU资格；其余对象域暂不并行铺开 |
| request-throttling-controller | 原有限流、多轮任务语义与请求排空 | 0.1.2 7ad7b12：Instance对象视图及版本化activate/drain/remove接公共SDK；107项Mac及Coder Linux通过、4可选跳过；原ThunderAgent核心不变；GitHub CI付款/额度导致未启动 | 本阶段作为共同配置，不改策略；SWE/B1暂停，非空Router恢复仍不支持 |
| [instance-controller](https://github.com/yancanmao/instance-controller) | 副本策略与扩缩协调 | 0.1.6 08f85c0：实际控制循环使用版本动作、丢回复后查原回执、排空进展重新采样、接收方世代替换拒绝；43项Mac/Coder Linux及Linux CI通过，策略公式未改 | 唯一研究主线：容量/启动/工作量资格，再做成熟策略匹配对照 |
| [kv-controller](https://github.com/yancanmao/kv-controller) | KV策略、后端能力与动作验证 | 0.1.4 a3a134d：Instance成员对象及原子条件动作、Job绑定与单向排空；45项Mac/Coder Linux及Linux CI通过；当前后端copy=false | 研究顺序第三项；本阶段保持原能力，真实KV与r19失败仍开放 |
| ride-cooperative-controllers | 历史来源与集成证据 | 保留原件，不再添加正式策略；r19失败不重标 | 供迁移比对，不维持第二份开发计划 |
| ride-website | 解释架构与真实验收范围 | 本轮不发布 | 后续明确授权后，依据实际结果更新 |

## 里程碑与验收

- [x] M0：独立仓库、公共RIDE开发范式、设计与架构图、中长期规划落盘。
- [x] M1（软件）：轻量SDK、原子条件启动/停止、操作身份与未知不重投；必要既有部署修复合并，原工作树未覆盖。
- [x] M2（软件）：独立实例Controller安装/插件发现、Ready后激活、准确Job停止、工具等待及双排空回归。
- [x] M3（软件）：独立KV包、后端接口、不支持动作前拒绝、UNKNOWN重启保护、源与目标覆盖验证及来源逐SHA。
- [x] M4（软件）：既有请求仓库的独立托管入口接公共SDK；事前声明模型池激活/排空/移除；旧任务续轮不被新任务等待阻塞；未知结果不猜排空；固定原版调度源逐SHA。新入口采用保守全局排空，原入口不替换；不宣称性能等价或原版运行态恢复。
- [x] M5.1（有界功能）：r36标准安装、独立Ray Jobs、身份/日志、三个Controller停止恢复、管理服务受控重启接管通过；限流层仅空状态重启，不含非空Router恢复、未知动作恢复或多副本高可用。
- [x] M5.2（功能）：r35两个Qwen3-0.6B模型，11次真实生成、4个任务/3个两轮；输出继承、稳定1→2→1、工具等待和排空通过；仅启动两个模型且原A保留，KV copy不支持前拒绝。没有答案正确率、真实KV复制或性能结论。
- [x] M5.2补充：r37新启动模型B经限流层实际承接新任务两轮，原A两个请求仍生成；缩回A后新任务两轮通过。9次真实生成、4个两轮任务，后端归属及输出继承已逐原件核验。r35/r36仅直连B的历史边界保留；r37是功能负载，无性能结论。
- [ ] M5.3：在已存在且明确支持的后端上验证真实KV动作/目标续轮/源保留。r19主动复制失败仍开放，不以扩大后端种类代替解决。
- [ ] M6：按[效果验证契约](CONTROLLER_EVALUATION.md)固定同条件完整批次、强基线、至少三组交替重复和留出；收益、负结果与开销分别报告，最后按明确授权发布。契约完成不等于实验完成。

## 历史验证证据与边界

来源、逐轮原始结果摘要、失败及负结果已按组织规范迁存到[固定路线图快照](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/5ce1289a705aa25269f350c29151556fa0864d53/reports/ride-control-plane-20261106/source/docs/architecture/CONTROLLER_ROADMAP.md)。[迁存清单](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/5ce1289a705aa25269f350c29151556fa0864d53/reports/ride-control-plane-20261106/manifest.json)记录原提交、原路径与SHA256；SDK早期软件记录及来源清单见[同目录原件](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/5ce1289a705aa25269f350c29151556fa0864d53/reports/ride-control-plane-20261106/source/docs/evidence/)。原字节保留，活动任务仍只由本表维护。

旧r19主动复制失败仍开放，非空Router恢复、跨服务一致快照、多副本高可用、真实KV动作与完整收益验收未完成。历史功能和软件结果不能外推新组合的硬件或性能资格；历史失败不重标，网站未发布。未知归属的资源和其他研究聊天保持独立。

## 2026-11-06 代码审查整改

本轮只做软件整改，不启动云端/NPU。审查六项负例原件保存在私有`runtime/code-review-20261106-r1/`，不回写旧结果。

- RIDE0.3.3：管理状态独占写锁、关闭后接管、持久写入与严格显式条件停止；Journal支持动作回执和业务状态同事务完成。
- Instance0.1.5：修复放置结果覆盖决策函数；自动控制前检查新能力，校验准确Job回执，停止确认后幂等移除Request/KV绑定。
- KV0.1.3：HTTP生命周期与copy/prepare绑定准确Job；排空单向转换、退役Job保护；可信COMPLETED旧记账恢复，UNKNOWN继续阻塞。
- Request0.1.1：迟到激活不撤销排空，退役Job不复活，同Job重复移除幂等；原调度核心及无限业务等待不变。

四仓固定源码前后逐文件SHA不变，本地标准检查通过：RIDE82、Instance39、KV43、Request105通过/4可选跳过；CLI/安装CLI/构建通过，跨包正常及丢回执协作通过。RIDE、Instance、KV新版Linux软件CI通过；Request新版CI因账户付款/额度未启动；组织数据review仍开放。最终源码与完整命令/日志存于私有`runtime/review-fixes-20261106-r1/final-software-receipt.json`，不发布原始环境。旧NPU0.3.2/0.1.3等结果不升级为新版本通过。该轮尚未实现通用对象schema及状态版本/CAS；后续软件进展见下。跨服务一致快照、真正UNKNOWN结果的外部核销、真实KV动作仍未完成；M5/M6硬件及收益边界保持。

## 2026-11-06 公共对象与条件动作：Coder软件资格

RIDE0.3.4/Instance0.1.6/KV0.1.4/Request0.1.2已分别提交，固定源码在9443标准CPU工作区`myc-ride-contract-1106-r1`完整运行原`tools/check.py`：90/43/45/107通过（Request另4可选跳过），CLI/安装CLI/构建及跨包CPU协作用例通过；源文件前后SHA不变。仅Instance成员视图实际接入，不以schema列出其他kind表示其功能已完成。动作身份/版本检查、本地转换与回执在接收方同事务提交；跨服务不原子。调用方UNKNOWN只查原回执，404不重投；排空另取实时观察，观察值不由成员版本冻结。

本轮0NPU、0模型/业务请求，实际Coder软件通过不等于新版Ray/NPU模型资格。模板CANN PYTHONPATH注入和pip依赖警告保留；另以`python -I`核已安装SDK无CANN路径且不导入Ray/Torch/vLLM/FastAPI。SSH曾返回Exceeded MaxStartups后恢复；首次上传脚本在远端语法检查失败，已证明目标不存在后仅修传输脚本，输入包/产品源码/绝对截止不变；两个运维回归通过，旧失败不重标。

43份原始回执逐文件SHA归档。临时工作区、Pod和专属PVC/PV已按精确ID确认全部删除，后备清理监控已退出；收尾回执见主计划与私有`runtime/state-contract-20261106-r1/`。下一项先在现有成功部署入口验新版独立Ray Jobs和真实扩缩/故障链，再补RuntimeState/ResourceBinding等确有使用者的对象视图；真实KV复制、外部UNKNOWN核销、跨服务一致快照、多副本高可用和收益对照仍开放。网站未发布、PR未合并。
