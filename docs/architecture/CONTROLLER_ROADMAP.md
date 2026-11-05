# RIDE 与 Controller 项目统一路线图

唯一技术设计：[INDEPENDENT_CONTROLLERS.md](INDEPENDENT_CONTROLLERS.md)。更新时间：2026-11-05。状态和来源按实际回执更新，不把计划/创建空仓/软件通过当全部完成。

## 项目对齐表

| 项目 | 本轮责任 | 下一项具体交付 | 当前状态 |
|---|---|---|---|
| ride | 公共 SDK、注册与管理、模型生命周期 | 轻量 import、条件启动/停止、操作身份、SDK 测试 | SDK software PASS (40 tests); installed-wheel PASS; cloud/NPU NOT_RUN; [PR #2](https://github.com/vLLM-HUST/ride/pull/2) |
| request-throttling-controller | 保留既有限流/多轮任务实现 | 核已有续轮/排空契约；接公共 SDK；独立发布 | 接入待验；旧合集FIFO缺陷不外推本仓；B1/SWE本轮不启动 |
| instance-controller | 独立扩缩 Controller | 独立包/仓库、entry point、SDK 调用、真实入口测试 | [Independent private repository](https://github.com/yancanmao/instance-controller); 9 tests and isolated installed-package fixture PASS; cloud/NPU NOT_RUN |
| [kv-controller](https://github.com/yancanmao/kv-controller) | 独立 KV Controller | 迁移已定接口与保守状态机，后端能力适配 | 独立仓库已推送；34项软件测试及跨包安装fixture通过；物理复制未修复 |
| ride-cooperative-controllers | 历史来源与集成证据 | 标记迁移、保持原件；停止在合集新增正式策略 | 88软件通过，整体硬件未验收 |
| ride-website | 解释架构与真实验收范围 | 消费本设计与证据，区分目标/实现/已测 | 本轮不发布；不写完成收益 |

## 按顺序推进的里程碑

- [x] M0：用户确认独立仓库与公共RIDE范式；技术设计、架构图及本表记录。
- [x] M1 (software)：RIDE SDK与安全模型生命周期。import无副作用/无Ray重依赖；条件启动原子核身份；重复/未知操作不重投；旧API兼容。
- [x] M2 (software)：实例Controller独立仓库。安装后由RIDE发现；启动/停止隔离；仅管理本次拥有的模型；工具等待和双排空回归。
- [x] M3 (software)：KV Controller独立仓库。独立安装且不import其他策略包；能力不支持/未知/完成语义保持；历史原件逐SHA。
- [ ] M4：请求Controller排空回归与公共契约接入。新任务不可阻断已有任务续轮；保留原ThunderAgent来源和与简单基线的区别。
- [ ] M5：跨仓标准云端CPU验证；再在独立冻结硬件窗口完成真实模型、缓存动作与自动1→2→1。缺项NOT_RUN。
- [ ] M6：同条件完整批次、原生强基线、至少3组交替重复；收益/负结果/代价分别报告；最后按明确授权更新网站。

## 已知失败及恢复边界

r19缓存主动复制失败、r21两项review缺陷保留；未修项不能被迁仓抹掉。Ray/平台身份门禁、无业务timeout、shuhao资源排除及已授权清理边界继续生效。旧截止不延长，下一窗口重新冻结；软件开发不需要等待硬件。发现新问题先保留最小复现，再修实现，不为过门禁修改预期。

软件核销补充：M1/M2勾选只指公共SDK和独立包的软件验收，真实Ray/NPU/收益仍由M5/M6核销。源码与完整命令见SDK_R22回执及实例仓库evidence。r21的FIFO缺陷在旧合集简单请求实现中，不外推原ThunderAgent；只有迁移该实现时必须携带修复，已有独立请求实现做对应契约回归。

M3 software receipt: [KV software-r23](https://github.com/yancanmao/kv-controller/blob/main/evidence/software-r23.json), commit6041ee6. Seven same-input core comparisons match; installed SDK/KV/Instance fixture passes normal scale-down and UNKNOWN-copy stop protection. Execution, model and storage are fixtures; cloud/NPU/performance NOT_RUN.
