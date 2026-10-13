> 当前部署边界：[复用已有 RayCluster](../reference/DEPLOYMENT_POLICY.md)。RIDE 只管理自己的 Jobs；不得按验收新建 Coder 模板／工作区。CPU 测试不替代真实 NPU 端到端验收。

> 本文涉及旧环境、旧入口或临时资源的内容为历史记录／早期规划，不是当前部署操作指南。已删除资源不得据此重建。

### 标准验收已进入 RIDE 代码，9450 重启接管通过

RIDE 新增 `ride verify`，代码内维护版本化契约 `ride.acceptance/v1`。所有标准使用固定检查 ID 和 PASS / FAIL / NOT_RUN，保存时间、被测实例、Ray Job ID、真实状态、原始日志和请求响应。普通 verify 只读检查，显式 --lifecycle 才停止/恢复指定 Controller。

云端用法：

```sh
ride verify --controller throttle-main --model-service model-cann --lifecycle --model qwen2.5-14b --output acceptance-before-restart.json
ride verify --controller throttle-main --model-service model-cann --model qwen2.5-14b --baseline acceptance-before-restart.json --output acceptance-after-restart.json
```

本轮在 9450 自有 workspace 实测：重复启动保留 Job、停止 Controller 后模型同一 Job 保持 Ready、恢复为新的 Ready Controller、真实请求成功。只重启 RIDE 管理 Job 后，管理 PID 11833→12636，持久化 run_id 不变，Controller Job 后缀 7a583b86 与模型 Job 后缀 212d5f7c 都没有改变，两个服务仍 Ready，真实请求再次成功。接管检查 PASS。11 项接口/契约回归均在云端执行通过。

部署生命周期、program 调度语义、源码身份、Web UI、访问边界和性能分别列在标准目录中。没有专项证据的项保留 NOT_RUN，不能因为部署通过就声称性能通过。complete 仅指部署检查完整，不代表全部专项。两段验收分别保留报告，不拼成单次全通过。当前 RIDE 是可用部署管理入口，仍不声称完整服务化平台或通用 Controller 类型已实现。

源码和规范：https://github.com/vLLM-HUST/ride/blob/main/docs/reference/ACCEPTANCE_CONTRACT.md
