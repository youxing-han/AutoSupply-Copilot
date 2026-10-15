"""Server-side capabilities shared by the local and public entrypoints."""
from __future__ import annotations

import os

PUBLIC_LLM_MESSAGE = "在线演示暂不支持本地Ollama问答。库存分析和 Python 模板报告仍可使用。"


def is_public_demo() -> bool:
    mode = os.environ.get("AUTOSUPPLY_MODE", "local").strip().lower()
    if mode not in {"local", "public"}:
        raise ValueError("AUTOSUPPLY_MODE must be local or public")
    return mode == "public"


def require_local_llm() -> None:
    if is_public_demo():
        raise RuntimeError(PUBLIC_LLM_MESSAGE)
