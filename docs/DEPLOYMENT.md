# Streamlit Community Cloud 部署

当前状态：正在准备发布，尚未填写在线演示地址。只有实际部署并验证后才记录 URL。

## 部署参数

- GitHub 仓库：`youxing-han/AutoSupply-Copilot`
- 分支：`main`
- 应用入口：`public_app.py`
- Advanced settings → Python version：`3.11`
- Secrets：留空；无需 API Key，也不要填写本机路径或 Ollama 地址。
- 依赖：根目录 `requirements.txt`；配置：`.streamlit/config.toml`。

## 登录后操作

1. 在 https://share.streamlit.io/ 登录，按平台提示授权需要部署的 GitHub 仓库。
2. 点击 **Create app**，选择从 GitHub 部署。
3. 填写上述仓库、分支和入口；在 **Advanced settings** 中选择 Python 3.11。
4. 确认应用为公开可访问，点击 **Deploy**，等待依赖安装和应用启动。
5. 打开平台实际返回的 URL。运行单物料、批量和动态分析，检查模板、PDF 下载与缺失 AI 提示。
6. 将经过验证的地址补入 README 和本文件，不把自拟子域名当作已部署地址。

Community Cloud 在 Linux 运行；应用使用基于 `__file__` 的项目相对路径，Excel 与 PDF
在内存生成，不依赖 Windows 快捷方式。公开入口固定关闭模型访问和 LangSmith 跟踪。
不需要个人电脑保持开机。平台免费资源、休眠与可用性以其当前政策为准，不承诺 SLA。

官方文档：
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies

## 更新和故障处理

推送到 `main` 后平台通常自动更新；修改依赖会重新构建。构建失败时先查看管理页面日志，
核对 Python 版本、依赖与入口。不要把含用户上传内容的日志贴到公开 issue。
禁止将入口改为本地 AI 服务代理；公开模式的核心功能不需要 Ollama。
