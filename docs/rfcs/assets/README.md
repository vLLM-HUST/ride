# RFC-0001 设计图

`0001-instance-policy.json`是布局和语义源文件，`.drawio`可在diagrams.net编辑，`.svg`用于RFC内嵌，`.png`用于预览。图为目标设计，不是运行或收益证据。

生成工具：drawio-diagram-engineer的`drawio_tool.py build <JSON> -o <输出目录> --name instance-policy --strict`。结构检查通过，未发现节点重叠或连接穿过节点。预览字体调整为标题17、说明13、边标签13、分组16，采用PingFang SC；SVG矩形直角。PNG由resvg-py 0.5.0从SVG以1500像素宽渲染。原生draw.io Desktop导出未运行。

交付前已实际打开PNG检查中文、标签、连线与裁切。后续编辑须同步更新四种格式；SVG/PNG的字体排版以实际渲染为准。

## Design 技术图

| 图 | 正文用途 | 可编辑与结构源 |
|---|---|---|
| [图2：请求数与工作量](0001-workload-design.png) | §3.3.1：相同请求数为何产生不同容量建议 | [draw.io](0001-workload-design.drawio)、[JSON](0001-workload-design.json) |
| [图3：启动时序](0001-startup-design.png) | §3.4.1：启动前瞻改变什么 | [draw.io](0001-startup-design.drawio)、[JSON](0001-startup-design.json) |
| [图4：容量与动作](0001-decision-design.png) | §3.6.1：何时扩缩、扩缩多少 | [draw.io](0001-decision-design.drawio)、[JSON](0001-decision-design.json) |

三张图均为假设算例/条件性机制示意，未运行性能模拟或硬件实验。生成命令与上文相同，`--name`取各文件名；三张新图的draw.io保留编译器默认字体及语义元数据，SVG按上文统一放大字体。PNG从SVG渲染，已逐图打开检查；原生Desktop导出未运行。

## Controller 主工作流

[四步工作流PNG](0001-controller-workflow.png)、[SVG](0001-controller-workflow.svg)、[draw.io](0001-controller-workflow.drawio)、[JSON](0001-controller-workflow.json)对应RFC §2.4，展开观测、聚合/时序决策、执行接口和验证反馈。语义源文件保留分组名称，展示时隐藏重复的分组标题；PNG以1950像素宽由SVG渲染。全部为拟议设计，非新链路已实现或TTFT收益证明。原生Desktop导出未运行。
