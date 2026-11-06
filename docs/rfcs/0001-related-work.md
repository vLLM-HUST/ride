# RFC-0001 Related Work：指标、性能建模与实例控制

关联：[RFC-0001](0001-instance-autoscaling.md)。核查日期：2026-11-06。本页保存相关工作及其对设计的影响，具体算法仍以RFC为准。

本轮收集8项学术/研究工作、10个社区issue和1个状态核验PR。学术部分选择系统领域代表性工作，不以未经核验的引用量声称影响力排名；Dapper为工业研究技术报告，不能列成同行评审会议论文。社区部分是公开讨论证据，issue作者报告、回复、已合并变更分别记录，不能与论文或本机实验互相替代。

## 1. 学术谱系：观测怎样进入控制决策

### 1.1 性能可预测性与多时间尺度资源管理

[Clockwork（OSDI 2020）](https://www.usenix.org/conference/osdi20/presentation/gujarati)从可预测的DNN执行时间构建满足时延目标的服务；[InferLine](https://arxiv.org/abs/1812.01776)将阶段profiling、配置规划与快速在线调整分离；[INFaaS（ATC 2021，Best Paper）](https://www.usenix.org/conference/atc21/presentation/romero)结合模型变体选择与多层扩缩。这些工作说明，资源控制需要需求、执行成本和业务约束，单个利用率阈值并不能表达全部目标。对RIDE的启发是明确观测/标定与策略/执行边界；这也是既有思想，不能将分层本身当新颖性。

### 1.2 LLM的阶段差异、动态状态与配置模型

[DistServe（OSDI 2024）](https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin)区分prefill和decode的时延与资源要求，优化满足TTFT/TPOT约束的goodput；[Llumnix（OSDI 2024）](https://www.usenix.org/conference/osdi24/presentation/sun-biao)利用运行时重调度与状态迁移应对异构、动态请求；[AlpaServe（OSDI 2023）](https://www.usenix.org/conference/osdi23/presentation/li-zhouhan)分析并行开销与突发负载统计复用的取舍。[Vidur（MLSys 2024）](https://mlsys.org/virtual/2024/poster/2667)则用profiling与预测模型模拟LLM推理和配置搜索。它们支持按阶段、工作量、状态与布局建立容量模型，也提醒我们：增加副本不等于既有任务与状态自动转移，离线模型准确性不能自动外推到新设备和业务混合。

### 1.3 从聚合指标走向请求路径证据

[Dapper（Google Technical Report，2010）](https://research.google/pubs/dapper-a-large-scale-distributed-systems-tracing-infrastructure/)讨论大规模分布式调用追踪、采样与低开销部署。它与本项目的关联在于用请求身份和阶段关联解释跨层等待；它不是LLM扩缩算法，也不意味着仅有trace就能自动识别因果根因。RIDE需要结合分层metrics、按请求/任务的阶段事件和有控制的验证，而非从几个相关曲线直接确定原因。

## 2. 学术工作对照表

| 工作/出处 | 论文中的核心机制或证据 | 与当前设计的关系及范围 |
|---|---|---|
| [InferLine：ML Prediction Pipeline Provisioning and Management for Tight Latency Objectives](https://arxiv.org/abs/1812.01776)，本轮读取arXiv v2（2020） | 低频规划器使用阶段profiling/离散事件模拟和配置搜索；高频tuner用traffic envelope/network calculus调整阶段副本 | 重点学习需求时间尺度、标定与在线控制分离；传统ML流水线假设不能直接搬成LLM容量常数。本轮以已读取预印本标识，不从其占位ACM模板推断正式venue |
| [Clockwork，OSDI 2020](https://www.usenix.org/conference/osdi20/presentation/gujarati) | 从DNN执行可预测性构造端到端时延管理和隔离 | 标定应解释执行时间；其确定性DNN前提不能直接推广到可变输出与混合批LLM |
| [INFaaS，ATC 2021](https://www.usenix.org/conference/atc21/presentation/romero) | 依据性能/精度约束选择模型变体，结合模型级和VM级扩缩；官网标Best Paper | 学习策略与多层资源执行分工；本期固定模型，不通过换精度/模型变体制造收益 |
| [AlpaServe，OSDI 2023](https://www.usenix.org/conference/osdi23/presentation/li-zhouhan) | 在模型并行开销与多模型突发流量的统计复用之间寻找布局策略 | 说明容量标定受布局与负载分布影响；本期同构单模型池，不实现其多模型放置优化 |
| [DistServe，OSDI 2024](https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin) | 区分prefill/decode及TTFT/TPOT目标，联合资源/并行度/放置优化goodput | 直接支持阶段化metrics和容量；本期不新增P/D分离或把其结果外推到共置Ascend |
| [Llumnix，OSDI 2024](https://www.usenix.org/conference/osdi24/presentation/sun-biao) | 对动态异构请求运行时重调度，以在线状态迁移支持均衡、隔离及优先级 | 后续状态感知重配置的重要对照；本期没有等价迁移能力，不宣称扩容能立即解除绑定任务压力 |
| [Vidur，MLSys 2024](https://mlsys.org/virtual/2024/poster/2667)，[论文](https://arxiv.org/abs/2405.05465)、[作者代码](https://github.com/microsoft/vidur) | 组合算子profiling与预测建模，模拟批次/调度/配置，进行满足约束的配置搜索 | 学习profiling→模型→决策验证；模拟要先验证目标硬件误差，不能代替真实完整任务和资源效果 |
| [Dapper，Google TR 2010](https://research.google/pubs/dapper-a-large-scale-distributed-systems-tracing-infrastructure/) | 跨组件请求追踪、关联、采样及低开销部署经验 | 支持分层时延与阶段证据设计；不等于完整根因自动诊断或LLM控制面实现 |

阅读深度：InferLine、Vidur、Dapper核了原文相关设计段落；其余五项核了会议官方摘要/元数据，机制限于其中明确描述。USENIX原文PDF本轮直接下载返回403，未伪称已精读全文。后续真正移植具体算法前须补对应章节、源码身份及许可/差异核对。

## 3. Dynamo社区：指标契约、排队与决策层评价

状态来自本轮GitHub API快照；open仅代表该讨论未关闭，不足以断言所有相关能力都未实现。以下数值和实验描述若有，只属于发帖者环境，本页不转录为本项目结果。

| 讨论 | 本轮状态与讨论实质 | 对RIDE的具体启发 |
|---|---|---|
| [#11947：Serving metrics over the runtime event plane](https://github.com/ai-dynamo/dynamo/issues/11947) | **open，DEP提案**。讨论TTFT/ITL、到达与长度分布等走事件通道，并在消费者内复用聚合库；关注Prometheus拉取链的陈旧性 | 输入新鲜度与聚合是控制语义的一部分。先测本系统端到端采样延迟，再决定pull/push，不能照搬提案的时限当保证 |
| [#10528：SLA autoscaling应考虑突发下的queue time](https://github.com/ai-dynamo/dynamo/issues/10528) | **open，功能请求**。作者报告v1.1.1中服务时间估计与客户端TTFT存在差距，提出加入队列/等待与尾时延 | 严格区分服务时间、引擎排队和端到端时延；历史版本报告不能概括成当前Dynamo所有模式都不看队列 |
| [#14238：ARIMA默认是否与last-value按GPU-hours比较](https://github.com/ai-dynamo/dynamo/issues/14238) | **open，有往返讨论**。讨论相同SLO下的资源成本；作者纠正自己对上游ARIMA重复拟合开销的推断。[贡献者回复](https://github.com/ai-dynamo/dynamo/issues/14238#issuecomment-5625999441)区分预测误差评分与决策层成本评分 | 预测准不等于扩缩划算；纳入简单last-value/常量持平基线，在相同约束下评时延—预约取舍。不能引用被作者纠正的开销数字攻击上游 |
| [#16468：Sidecar observability](https://github.com/ai-dynamo/dynamo/issues/16468) | **open，DEP与分项跟进**。讨论指标语义保持、trace关联、不同引擎覆盖、重复采集与开销；正文选择直接scrape引擎并暂缓re-export | 适配层先列语义与能力差异，不因都叫metrics就视为等价。不同部署形态要独立验收，不能由集成模式外推sidecar |
| [#17383：fresh-token估计再次应用缓存折扣](https://github.com/ai-dynamo/dynamo/issues/17383) | **open，作者bug报告，0评论**。对已扣除cache的scheduled token和未解析cache的queued token提出口径失配疑问；本轮未独立复现 | 指标须标明raw/fresh/cached语义，防止重复折扣。可用来制定回归用例，不能称上游已确认根因或修复 |

正式实现与讨论要分开读：[Dynamo Planner v1.6.1设计](https://docs.nvidia.com/dynamo/v1.6.1/knowledge-base/modular-components/planner/planner-design)是当前已核设计来源；上述历史报告、DEP和局部疑问不能覆盖全部版本与运行模式。

## 4. llm-d社区：启动中的容量、闭环Agent与可解释控制

| 讨论 | 本轮状态与讨论实质 | 对RIDE的具体启发 |
|---|---|---|
| [autoscaling #1603：Pending-aware扩缩](https://github.com/llm-d/llm-d-autoscaling/issues/1603) | **open，作者报告实验及后续结果**。将正在启动的pod与新到达需求区分，讨论等待新容量时的重复扩容及响应速度/资源成本 | starting需计预算但不是Ready；比较稳定窗口与pending-aware逻辑。其H100实验与阈值未在本项目复现，不能直接复制为参数 |
| [autoscaling #1606：Agentic流量是闭环，需关注SLO](https://github.com/llm-d/llm-d-autoscaling/issues/1606) | **open，作者结果及新策略提议，0评论**。指出闭环请求由完成/工具等待反馈产生，失败率和有界队列可能掩盖体验问题，提出SLO反馈及闭环标定 | Agent不能仅靠队列/完成率验收；工具等待不代表模型缺容量。SLO反馈应作为相关候选/基线，不把一帖结论写成所有Agent必须用某一算法 |
| [autoscaling #1607：Agentic inflight autoscaling评测计划](https://github.com/llm-d/llm-d-autoscaling/issues/1607) | **open，评测提案，0评论**。讨论活跃turn与存活session不同、输入/cache差异和工具等待；部分估计明确未测 | 记录请求、program/会话与工具等待分母，采用任务进展和时延共同判读；离线估计和计划不是实测完成 |
| [benchmark #2017：采集token-aware的inflight tokens](https://github.com/llm-d/llm-d-benchmark/issues/2017) | **open，指标缺口请求，有认领回复**。指出图有副本变化却缺prefill触发输入，难以解释为什么扩容 | 必须把原始输入、归一化压力、阈值/子建议、最终目标、实际Ready、动作结果放在同一时间轴；副本曲线不是策略生效证据 |
| [autoscaling #1572：Async/batch驱动扩缩](https://github.com/llm-d/llm-d-autoscaling/issues/1572) | **open，分阶段提案/进展**。以broker backlog及deadline接近度服务批处理，区分生产者计算需求和执行方应用副本 | 支持场景目标/观测可替换的方向；异步batch不等于异步RL，训练消费、样本接纳和权重版本仍需另行定义 |

### 4.1 已核实的上游状态纠正

[llm-d PR #2956：Remove experimental flag from Token-Aware Autoscaling](https://github.com/llm-d/llm-d/pull/2956)的API显示`merged=true`，合并时间2026-10-28T14:33:50Z，merge commit为`107b21a58c9d7bf49631fc154f4b0560d0710a29`。正文链接实验讨论#1590；本轮未复算其数据，不把PR描述中的优势当通用性能保证。

前序RFC固定引用`343d9be9813020f43aeb5a5b97cb459102bb5893`，该版本确实带Experimental标记；将这一历史标记概括为上游当前状态不充分。现明确区分固定来源与已合并主线变更。标记移除不能证明当前Ascend可用、所有工作负载获益或RIDE移植完成，尚未核具体发布tag包含关系。

## 5. 对当前方案的影响与阅读顺序

第一优先读InferLine、DistServe、Llumnix，以及Dynamo #11947/#10528和llm-d #1603/#1606/#2017。它们最直接对应“合适指标→容量模型→时序决策→解释动作”这条链。Vidur用于性能模型的标定/误差边界，Dapper用于请求路径证据；INFaaS、AlpaServe、Clockwork补齐资源层次、布局与可预测性的背景。

当前可确定的设计要求：

1. 指标契约必须记录来源、阶段、raw/fresh/cache语义、窗口、新鲜度、身份及覆盖；输入不可信时不能填0继续决策。
2. 将需求压力、启动中容量及真实Ready分开；保留执行与诊断证据链，对齐观测、各子建议、动作和业务结果。
3. 预测的收益按相同SLO约束下的累计预约与任务完成评价；加入简单预测基线，不只优化预测误差。
4. 后续Agent研究要单列闭环反馈和工具等待；当前在线首轮不自动升级为Agent/RL实验，暂停的B1/SWE也不恢复。
5. 将SLO反馈、合理调节的队列/计数策略及pending-aware策略列入待选对照，待能力与场景明确后冻结；本次仅增补Related Work，不静默替换RFC第7节控制律。

现阶段可主张的是“设计与上述文献/社区问题对齐”。指标驱动控制、按阶段建模、快慢控制循环及状态感知调度均有明确先例。尚无证据支持RIDE算法新颖性、根因自动识别或正收益；若未来研究贡献成立，必须来自更具体的问题、机制和实测。

## 6. 核查与局限

本轮读取会议官网、作者论文/仓库及GitHub issue正文、评论和PR API；未运行模型或资源实验，未移植代码。PR合并字段单独核查，不由closed推断merged。#1606/#1607的独立详情读取遇到临时连接失败，正文和open状态由当次GitHub搜索API完整条目核对；其余选定讨论读取了独立详情，部分评论读取失败处不据此推断社区共识。

这是一批按当前设计问题筛选的相关工作，不是穷尽检索。未核引用量，五篇会议论文仅核官网摘要而非全文；没有将作者测量升级为我们的性能结论。后续代码复用仍需逐文件来源、许可证、适配差异和实际运行验收。
