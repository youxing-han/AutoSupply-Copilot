# Open-source Attribution and Third-party Components

AutoSupply Copilot is derived from Cindy Aprilia's SupplyChainAgenticAI:
https://github.com/cinapr/SupplyChainAgenticAI

The inherited development remote is `youxing-han/SupplyChainAgenticAI`. The original MIT license and `Copyright (c) 2026 Cindy Aprilia` notice are retained in `LICENSE`.

The current derivative extends the example with automotive simulation data, inventory rules, a four-node workflow, dynamic planning, mitigation comparison and a Chinese-language workbench. The public snapshot excludes the upstream food-supply experiments, videos and historical reports. Changes to portfolio presentation do not change the project's origin or license obligations.

## Direct Python Dependencies

| Component | License |
|---|---|
| Streamlit | Apache-2.0 |
| LangGraph | MIT |
| langchain-ollama | MIT |
| pandas | BSD-3-Clause |
| Plotly.py | MIT |
| openpyxl | MIT |
| ReportLab | BSD |
| defusedxml | PSF |

These labels were checked against installed package metadata and bundled notices at release preparation. Dependency distributions retain their own license files. This repository declares and uses the packages; it does not copy virtual environments or vendored library source. The installed environment also contains transitive dependencies. See the release audit for the scope and limitations of that review.
