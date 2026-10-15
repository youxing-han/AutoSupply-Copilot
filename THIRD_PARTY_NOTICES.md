# 开源来源与第三方组件

AutoSupply Copilot 基于 Cindy Aprilia 的 SupplyChainAgenticAI 二次开发：
https://github.com/cinapr/SupplyChainAgenticAI

本地继承仓库 remote 为 youxing-han/SupplyChainAgenticAI。保留上游
`LICENSE` 的 MIT 许可及 `Copyright (c) 2026 Cindy Aprilia` 声明。
汽车零部件模拟数据、库存规则、四节点工作流、动态计划、方案比较及中文工作台
为当前二次开发的内容。发布快照不包含上游食品供应实验、视频和旧报告。

直接 Python 依赖：

| 组件 | 许可 |
|---|---|
| Streamlit | Apache-2.0 |
| LangGraph | MIT |
| langchain-ollama | MIT |
| pandas | BSD-3-Clause |
| Plotly.py | MIT |
| openpyxl | MIT |
| ReportLab | BSD |
| defusedxml | PSF |

这些许可来自安装包元数据和包内声明；依赖自身的许可证随安装包保留。
公开快照仅声明和使用这些包，不把虚拟环境或包的源码复制进项目。
完整安装环境包含传递依赖，许可证核对记录见发布检查记录。
