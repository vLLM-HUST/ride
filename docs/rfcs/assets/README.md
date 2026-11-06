# RFC-0001 设计图

`0001-instance-policy.json`是布局和语义源文件，`.drawio`可在diagrams.net编辑，`.svg`用于RFC内嵌，`.png`用于预览。图为目标设计，不是运行或收益证据。

生成工具：drawio-diagram-engineer的`drawio_tool.py build <JSON> -o <输出目录> --name instance-policy --strict`。结构检查通过，未发现节点重叠或连接穿过节点。预览字体调整为标题17、说明13、边标签13、分组16，采用PingFang SC；SVG矩形直角。PNG由resvg-py 0.5.0从SVG以1500像素宽渲染。原生draw.io Desktop导出未运行。

交付前已实际打开PNG检查中文、标签、连线与裁切。后续编辑须同步更新四种格式；SVG/PNG的字体排版以实际渲染为准。
