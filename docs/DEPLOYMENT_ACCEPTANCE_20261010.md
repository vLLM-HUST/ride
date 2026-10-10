# 初始部署验收：2026-10-10

作废：用户纠正部署归属。平台共享服务不是产品目标，已撤销新增网关 location 并禁用独立宿主机服务。下列记录仅保留错误部署的历史，不能作为 workspace 产品验收。下一验收必须使用 workspace 内 RIDE 和 Coder App。

RIDE 初始只读 UI 已部署到用户授权的 9450 网关后，独立 CPU systemd 服务，不申请 NPU，不修改当前 9443 Ray 性能任务。

实际验证：systemctl is-active ride=active；应用 /healthz 正常；/api/v1/status 返回真实 observed_at 和空 controllers；nginx -t 通过；Coder /healthz=200；未认证公网 /ride/=401；写 POST=405。

浏览器通过 SSH 隧道访问同一远端应用，页面标题 RIDE 控制平面、真实状态时间及 inspect=true/start_controller=false/mutate=false 正确呈现。公网浏览器未登录返回401，符合认证保护；尚未完成登录后公网端到端验收。

首次紧随启动的探针连接拒绝，后续服务 active、API正常，属启动未就绪；不能将首次探针记为成功。

尚未验收：真实 controller 接入与启停、RayCluster 应用部署与稳定代理、停止/恢复、多用户权限。当前为可访问的部署原型，不是完成的 RIDE 平台。

回滚：撤销新增 /ride/ location 并 nginx -t/reload，停止独立 ride 服务。部署前网关备份保留在服务器 /etc/nginx/coder-gateway.before-ride-20261010。不删除任何工作区或持久化数据。
