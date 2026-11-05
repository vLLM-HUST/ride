# RIDE 与独立 Controller：统一技术设计

状态：2026-11-05 用户已确认的目标架构；按下方验收逐项实现。图中的目标模块不等于已全部实现。执行顺序与各项目状态唯一记录在 [统一路线图](CONTROLLER_ROADMAP.md)，不在各仓库复制另一份独立计划。

## 1. 要实现什么

每类 Controller 都是独立 Git 仓库、独立 Python 包和独立运行进程，依赖公共 RIDE SDK；RIDE 管理服务把 Controller 和 vLLM 实例托管到已有 Ray 集群。Controller 负责策略，RIDE 负责生命周期，Ray 负责执行。共享开发契约，不共享业务实现或 Python 内存状态。

![目标架构](assets/architecture.svg)

[编辑图](assets/ride-architecture.drawio) · [PNG](assets/architecture.png) · [结构源文件](assets/architecture.json)。白底、细线、橙色强调，依赖、管理调用和推理数据流按区域分开；后续在该源图上修改。

## 2. 仓库和依赖

| 仓库 | 内容 | 依赖方向 |
|---|---|---|
| ride | SDK、公共协议、CLI、管理服务、Ray 执行适配、模型生命周期 | 不依赖具体 Controller 策略 |
| request-throttling-controller | 原有限流/多轮任务控制、其 RIDE 适配与测试 | 依赖 ride；不依赖其他 Controller 包 |
| instance-controller | 副本数策略、启动/就绪/排空/停止的协调循环 | 依赖 ride；通过 HTTP 调用请求/KV Controller |
| kv-controller | KV 策略、观测与动作验证；底层适配器 | 依赖 ride；按需依赖 LMCache、Mooncake 等 |
| 其他 Controller | 需要独立发布/运行的策略各自建仓 | 遵循相同契约，不统一塞回合集 |

旧 ride-cooperative-controllers 保留历史原件与已验证实现，作为迁移来源和集成证据，不作为未来所有策略的发布单元。迁移记录源提交/文件 SHA、必要差异和独立测试，不能把拷贝后的软件通过当实机通过。

## 3. RIDE 是库，也是管理服务

`import ride.sdk` 只加载轻量协议和客户端，不导入 Ray/vLLM/缓存 SDK，不启动服务、不提交作业。一个工作区使用明确地址和状态目录的 RIDE 管理服务；禁止每个 Controller import 后各自创建 Runtime。RIDE 不是平台级共享管理员服务。

管理端通过 `ride.controllers` entry point 发现轻量适配器。每个适配器提供 `command(spec)` 与 `probe(spec)`；重依赖只在对应 Controller Job 环境加载。包版本、来源、配置 SHA 与运行环境固定，Controller type 和运行 instance 分开。公共协议版本独立声明。

SDK 提供：模型管理客户端、Controller 发现/调用客户端、身份/配置契约、操作结果、持久化动作记录等公共工具。先提供实际需要的最小接口，不引入大而全的 Controller 基类或插件自动下载器。

## 4. 数据流与控制流

业务：客户端 → Request Throttling Controller → vLLM。管理服务不转发每次推理。调用方显式提供多轮任务身份，任务结束显式 release；工具等待不等于任务结束。

控制：Controller 观测 → 自己决策 → SDK 调用 RIDE 或其他 Controller 的 API → 执行方返回动作身份与状态 → 调用方验证实际结果。Controller 不直接创建 RayCluster、Coder workspace 或平台存储。

缓存数据由现有引擎/后端搬运，KV Controller 不自行实现传输引擎。接口要表达能力和完成语义，不能把普通健康、登记或“任务已受理”当真实完成。

## 5. 状态与动作的唯一管理者

| 状态/动作 | 唯一管理者 |
|---|---|
| 请求槽位、任务归属、请求排空 | Request Throttling Controller |
| 缓存策略、KV 动作及排空状态 | KV Controller / 对应后端适配器 |
| 期望副本数、扩缩协调 | Instance Controller |
| 实际 Controller/model Job 身份、启停、日志 | RIDE 管理服务 |
| 实际资源调度与进程执行 | Ray；平台资源由已有平台管理 |

停止模型必须经过请求排空和 KV 动作排空，并核准确 Job 身份。启动必须带本次创建操作身份和原作业身份条件，在管理端同一临界区校验，不能仅先 GET 再 POST。已完成操作返回原结果；提交结果未知不重投。独立仓库不意味着自动具备多副本高可用，首版各 Controller 单写者、独立状态文件。

## 6. 统一接口最小集合

- 开发/部署：固定配置、独立进程入口、适配器注册、协议版本。
- 观察：health、identity、status、capabilities、标准输出日志；控制进程健康与底层功能就绪分开。
- 生命周期：启动条件、操作 ID、实际 Job ID、查询、带 expected_job_id 的停止。
- 协作：按身份发现服务端点；只通过有版本的 API 调用，不 import 对方策略代码。
- KV：capabilities、连续覆盖 lookup、保源完成 copy、health。未知观察不填 0；不支持动作提前拒绝；提交未知保留记录。

旧接口兼容；新安全能力通过 capability 显式协商。业务请求不设 timeout、不自动重试。管理探测和整体资源期限另计，不能混成业务 SLO。

## 7. 真实现状与已知问题

已有：RIDE 独立包、CLI、entry point、Ray Job 生命周期；旧合集软件 88 项通过；r12真实请求/路由/接管，r19五策略与后端独立Ray部署及源512-token生成/登记。

未完成：完整公共 SDK、独立 Controller 仓库迁移、跨仓兼容验收、真实 KV 主动复制、真实自动扩缩和收益。r19 LMCache Ascend 主动复制 FAIL 原件保留；本轮不通过继续扩大后端种类代替解决接口与验证。

review 两项必须修：全局 FIFO 在排空时可能阻塞已有任务续轮；模型启动 GET→POST 存在归属竞态。复现为本地软件证据，不指称线上事故。前者归请求仓库，后者由 RIDE 条件启动接口和实例仓库共同修复。

## 8. 验收顺序

先统一协议与失败回归 → 独立安装/注册/发现/启停/重启状态 → 两类 Controller 的跨进程协作 → 真模型动作与输出正确 → 完整批次强基线收益。每项按实际证据核销。CPU/Mock 不充当 NPU；固定 RayCluster 下停止模型 Job 不等于释放平台申请卡时。

B1/SWE 线保持用户要求的暂停；其他研究线和共享平台工作不自动并入。当前文档/软件开发不授权新平台变更。资源实验沿已明确的具体范围，重新冻结身份与截止，结束归档清理。
