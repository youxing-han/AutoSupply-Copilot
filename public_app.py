"""Streamlit Community Cloud entrypoint; never connects to a local model."""
import os

# These process-wide capabilities are fixed before importing LangGraph.
os.environ["AUTOSUPPLY_MODE"] = "public"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

from app import render_app

render_app()
