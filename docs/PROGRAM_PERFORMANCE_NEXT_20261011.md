# 三方 program 性能诊断计划（2026-10-11）

目标：验证并发多轮 program、工具等待和KV承压下，Request Throttling能否提高有效吞吐并接近官方。
普通无身份请求旁路短测不作为调度性能验收。

复用9450 admin/ride-shared-myc标准RayCluster。RIDE仍管理模型和产品Controller；
官方对照与工作负载客户端是独立命名Ray Job，不创建新基础设施。
只替换已归档的本轮pressure-qwen及pressure-request-throttling-v2，
新实例program-scan-qwen及program-scan-controller由RIDE部署，显式开启测试prefix-cache重置接口。
不停止主模型、Demo、主Request Throttling，不重启集群。

固定官方7ddc861，双方no-keepalive/timeout900，无新增重试。
真实Qwen3-0.6B，模型长度2048，KV64×128=8192token。
先三方2program×3轮smoke。通过后并发program指数点8/32/128，
每方每点120秒，窗口40–120秒；每次重置实际prefix cache。
512个固定输入program，4轮：首轮512输入token，后续每轮128新增token、64输出token，轮间3秒工具等待。
发送器复用新Controller仓库的replay_sessions；固定输出占位使后续输入跨策略完全一致。
此受控输入保留多轮前缀增长，但不是自然模型输出历史；后续自然历史对照另验。

任意请求失败或输入/输出token偏差使该项FAIL，保存所有服务日志，不选择性删除错误。
CSV/图展示成功steps/min、完成比例、已完成program延迟、KV/命中和两层队列。
短窗口单轮只诊断趋势，不声明完整Figure1a复现；不拼旧14B/9443数字。
最低目标是同轮Our Controller超过vLLM，达到官方90%；达不到就定位原因，不调整门槛。

预计扫描基础测量18分钟，另加smoke、模型准备和排空；实际进度按Ray任务更新。
