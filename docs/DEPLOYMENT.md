# Streamlit Community Cloud Deployment

Live application: https://autosupply-copilot.streamlit.app/

Public repository: https://github.com/youxing-han/AutoSupply-Copilot

The initial deployment and core online acceptance were completed on 2026-10-15. These are dated observations, not a claim of a fresh cloud acceptance run on every documentation update. See `RELEASE_AUDIT.md`.

## Deployment Settings

- Repository: `youxing-han/AutoSupply-Copilot`
- Branch: `main`
- Entrypoint: `public_app.py`
- Python: `3.11`
- Secrets: empty; do not add personal paths, a local Ollama URL or model API keys.
- Dependencies: root `requirements.txt`; runtime configuration: `.streamlit/config.toml`.

## Deploy or Inspect

1. Sign in at https://share.streamlit.io/ and authorize the intended GitHub repository.
2. Choose **Create app**, then deploy from GitHub.
3. Enter the repository, branch and entrypoint above; select Python 3.11 in advanced settings.
4. Keep the app publicly accessible and deploy. Wait for dependency installation and startup.
5. Open the actual URL returned by the platform and test single-SKU, batch and dynamic planning, imports, downloads and the unavailable-AI notice.

The Linux runtime uses project-relative paths and in-memory Excel/PDF generation. The public entrypoint disables local model access and model tracing. The developer's computer need not stay on. Free-tier availability and sleep behavior depend on platform policy; no SLA is promised.

## Updates

The original development checkout keeps its old `origin`. Its additional `public` remote maps `codex/public-release:main`, an independently initialized, reviewed snapshot. Do not push the development `main` directly to the public repository: it contains a different history and unnecessary development files.

The ignored `.runtime/public-release` checkout is a local publishing workspace. Only committed allowlisted application files are exported, with a SHA-256 manifest. Alternatively, clone the public repository separately to maintain it. No history rewrite or force push is required for routine updates.

Community Cloud normally rebuilds or reruns after changes reach the deployed branch. Dependency changes require installation. Check logs for build failures, Python-version differences or invalid entrypoints. Do not post user-upload content or credentials in public issues or logs. Never turn the public app into a proxy to the developer's Ollama service.

## Initial Acceptance Evidence

The initial Ubuntu run executed 201 tests with five Windows-only skips and no failures:
https://github.com/youxing-han/AutoSupply-Copilot/actions/runs/38668565677

The original final local suite passed 202 tests after link and screenshot checks were added. Later documentation changes have their own test records; see repository Actions for the corresponding Linux status.

Online acceptance included stock changes, a 12-item batch, Excel/CSV uploads, default dynamic planning, a five-sheet delay workbook, mitigation comparison, session separation and actual PDF/Excel downloads. A fresh unauthenticated HTTP session reached the public app without a sign-in redirect.

Official deployment reference:
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
