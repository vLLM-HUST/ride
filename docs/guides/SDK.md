# 独立 Controller 的 RIDE SDK

这是0.3.0开发分支的最小公共SDK，协议版本1。实现不等于已获云端/NPU资格；当前验证范围见[跨项目路线图](../architecture/CONTROLLER_ROADMAP.md)。

```python
from ride.sdk import RideClient

ride = RideClient("http://ride-management:19100")
result = ride.models.start(
    "myc-model-a", model_spec,
    operation_id="persist-before-call-unique-operation",
    expected_job_id=None,  # 明确要求当前没有这个模型Job
)
model = ride.models.describe("myc-model-a")
# 自动停止前由对应Controller完成请求和KV双排空。
ride.models.stop("myc-model-a", expected_job_id=result["job_id"])
```

导入SDK不启动服务，不加载Ray、vLLM、Torch或FastAPI。客户端不自动重试，默认HTTP无限等待；管理探测可显式设置单独timeout。SDK不会自动创建工作区/集群，也不会替调用方做策略决策。

## API与安全条件

- `GET /api/v1/capabilities`：不触发模型/Job健康查询的纯能力端点；返回protocol_version及条件启停能力。
- `POST .../model-services/{id}/start`：新请求体为`{spec,operation_id,expected_job_id}`。SDK先核版本/能力；服务端在单管理实例锁内比较原Job身份后再提交。
- 同操作ID/同载荷返回原Job；同ID异载荷409；已提交但结果未知409，不重投。`GET /api/v1/operations/{operation_id}`查询原Job及状态，响应不泄露原模型spec。
- 停止仅接受准确expected_job_id；错误身份拒绝。旧平面start/stop API保留兼容，新包不使用无条件停止。残缺新请求体拒绝，不能降级到旧API。
- `ride.controllers` entry point继续提供command/probe。`PythonControllerAdapter`复用冻结配置SHA、进程命令和身份探测；具体Controller只声明module和role，业务循环归自己。
- `Journal`提供独立SQLite操作记录；实例不能共享同一状态文件。它不构成多管理副本一致性或任意外部动作的exactly-once保证。

SDK也提供PeerClient、ControllerAdapter协议、load_configuration及Controller端点查询。调用其他Controller只通过管理端发现的端点与公开API，不import对方策略。

## 兼容与限制

本分支从已提交071976e隔离开发，未覆盖原工作树的local执行、硬件运维等未提交功能。正式部署前要整合已成功的运行闭包并重过云端入口，不把该分支的软件验收当替换现有实机环境的许可。RIDE现有管理服务为单实例单写者；原子比较只覆盖同一个Runtime，不宣称跨多个管理进程的分布式CAS或高可用。

测试：`PYTHONPATH=src python -m pytest -q tests`，再build并在干净环境安装wheel，核`import ride.sdk`、CLI与独立插件发现。测试内Ray/model执行均为fixture，0真实模型请求。
