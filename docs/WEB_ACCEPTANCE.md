# Web UI 部署与验收契约

本阶段只交付只读管理服务与 UI，不把 UI 可访问等同于 controller 生命周期接入或性能验收。

入口必须是所属 workspace 的 Coder App，由 Coder 生成访问 URL；不得手拼或使用平台级 /ride/。应用内部 API 为 /api/v1/status、/api/v1/controllers；存活探针 /healthz 不代表被管理 controller 就绪。

Ray 部署必须绑定自有 head 的 Service/端口或 Coder App，代理到 RIDE 应用端口；不绑定临时 Pod IP，不把 8265 Dashboard 当 RIDE UI。Service 的 selector 必须只选择对应运行，端点为空时显示不可用。停止 Ray 后 UI 不得继续显示健康缓存。

验收：未登录公网请求拒绝；登录后 HTML、JS 请求与 API 正常；刷新读取真实时间与状态；后端不可达显示 Unavailable；所有写接口拒绝；浏览器实际检查；UI 页面和 API 内容一致。允许的访问权限由网关明确配置。单机 UI 通过后，另做真实 Ray 应用部署与停止/恢复验证，未运行标 NOT_RUN。

后续 controller 启动、禁用操作必须实现授权、控制权和操作回执后再开放。不会通过演示数据填充运行状态。
