"""Batch import, validation, and LangGraph execution for AutoSupply Copilot."""

from __future__ import annotations

import io
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from agents import build_supply_chain_graph, create_initial_state
from supply_data import NORMAL_SUPPLY, generate_automotive_supply_data
from upload_safety import validate_upload, validate_frame_size, validate_worksheet_size


MAX_BATCH_SKUS = 50
BATCH_DATA_VERSION = 2
SUPPLIER_STATUS_ALIASES={'正常交付':'NORMAL','正常':'NORMAL','交付延迟':'DELAYED','存在风险':'AT_RISK','供应中断':'DISRUPTED','停止供货':'STOPPED','暂无供给':'UNAVAILABLE'}
CRITICALITY_ALIASES={'低':'LOW','中':'MEDIUM','高':'HIGH'}
SUPPLIER_STATUSES = {
    "NORMAL",
    "DELAYED",
    "AT_RISK",
    "DISRUPTED",
    "STOPPED",
    "UNAVAILABLE",
}
CRITICALITY_LEVELS = {"LOW", "MEDIUM", "HIGH"}
REQUIRED_COLUMNS = (
    "part_code",
    "part_name",
    "supplier",
    "current_stock",
    "daily_usage",
    "lead_time_days",
    "supplier_status",
    "criticality",
    "backup_supplier",
    "backup_supplier_available",
    "destination_line",
    "unit_cost",
    "safety_days",
)
NUMERIC_COLUMNS = (
    "current_stock",
    "daily_usage",
    "lead_time_days",
    "unit_cost",
    "safety_days",
)
TEXT_COLUMNS = (
    "part_code",
    "part_name",
    "supplier",
    "destination_line",
)
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def build_batch_template() -> pd.DataFrame:
    """Return a five-row fictional automotive template."""

    template = generate_automotive_supply_data(NORMAL_SUPPLY)
    return template.loc[:, REQUIRED_COLUMNS].copy()


def template_csv_bytes() -> bytes:
    return (TEMPLATE_DIR / "autosupply_batch_template.csv").read_bytes()


def template_xlsx_bytes() -> bytes:
    return (TEMPLATE_DIR / "autosupply_batch_template.xlsx").read_bytes()


def read_batch_file(file_name: str, content: bytes) -> pd.DataFrame:
    """Read a user-provided CSV or XLSX payload without touching disk."""

    suffix = Path(file_name).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise ValueError("仅支持 .xlsx 或 .csv 文件。")
    validate_upload(content, xlsx=suffix == ".xlsx")
    source = io.BytesIO(content)
    if suffix == ".csv":
        try:
            frame = pd.read_csv(source, encoding="utf-8-sig", nrows=MAX_BATCH_SKUS + 1)
        except UnicodeDecodeError:
            source.seek(0)
            frame = pd.read_csv(source, encoding="gb18030", nrows=MAX_BATCH_SKUS + 1)
        validate_frame_size(frame, MAX_BATCH_SKUS)
        return frame
    if suffix == ".xlsx":
        with pd.ExcelFile(source, engine="openpyxl") as workbook:
            if (len(workbook.sheet_names) > 2 or
                    any(name != "填写说明" for name in workbook.sheet_names[1:])):
                raise ValueError("批量分析仅接受一个数据工作表和可选填写说明页；多表计划请使用动态物料计划。")
            sheet = workbook.book[workbook.sheet_names[0]]
            validate_worksheet_size(sheet, MAX_BATCH_SKUS)
            headers = [c.value for c in next(sheet.iter_rows(min_row=1, max_row=1))]
            if len(headers) != len(set(headers)):
                raise ValueError("Excel 字段名不能重复。")
            frame = pd.read_excel(workbook, nrows=MAX_BATCH_SKUS + 1)
        validate_frame_size(frame, MAX_BATCH_SKUS)
        return frame
    raise ValueError("仅支持 .xlsx 或 .csv 文件。")


def _parse_boolean(value: Any) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value) == 1:
            return True
        if float(value) == 0:
            return False
    normalized = str(value).strip().lower()
    truthy = {"true", "yes", "y", "1", "是", "可用"}
    falsy = {"false", "no", "n", "0", "否", "不可用"}
    if normalized in truthy:
        return True
    if normalized in falsy:
        return False
    return None


def validate_batch_dataframe(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame | None, list[str]]:
    """Validate and normalize an uploaded batch before any workflow runs."""

    errors: list[str] = []
    if frame.empty:
        return None, ["上传文件没有可分析的数据行。"]
    if len(frame) > MAX_BATCH_SKUS:
        return None, [f"单次最多分析 {MAX_BATCH_SKUS} 个 SKU，当前文件包含 {len(frame)} 行。"]
    try:
        validate_frame_size(frame, MAX_BATCH_SKUS)
    except ValueError as exc:
        return None, [str(exc)]

    normalized = frame.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    missing = [column for column in REQUIRED_COLUMNS if column not in normalized]
    if missing:
        return None, ["缺少必要字段：" + "、".join(missing)]

    normalized = normalized.loc[:, REQUIRED_COLUMNS].copy()
    if len(normalized) > MAX_BATCH_SKUS:
        errors.append(
            f"单次最多分析 {MAX_BATCH_SKUS} 个 SKU，当前文件包含 {len(normalized)} 行。"
        )

    for column in TEXT_COLUMNS:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        invalid_rows = normalized.index[normalized[column] == ""].tolist()
        for row_index in invalid_rows:
            errors.append(f"第 {row_index + 2} 行的 {column} 不能为空。")

    duplicate_mask = normalized["part_code"].str.upper().duplicated(keep=False)
    if duplicate_mask.any():
        duplicates = sorted(
            set(normalized.loc[duplicate_mask, "part_code"].str.upper())
        )
        errors.append("SKU 编码重复：" + "、".join(duplicates))

    for column in NUMERIC_COLUMNS:
        numeric = pd.to_numeric(normalized[column], errors="coerce")
        invalid_mask = numeric.isna() | ~numeric.map(math.isfinite) | (numeric < 0)
        for row_index in normalized.index[invalid_mask]:
            errors.append(f"第 {row_index + 2} 行的 {column} 必须是有限的非负数。")
        normalized[column] = numeric

    normalized["supplier_status"] = (
        normalized["supplier_status"].fillna("").astype(str).str.strip().str.upper()
    ).replace(SUPPLIER_STATUS_ALIASES)
    for row_index, value in normalized["supplier_status"].items():
        if value not in SUPPLIER_STATUSES:
            errors.append(
                f"第 {row_index + 2} 行的 supplier_status 无效：{value or '空值'}。"
            )

    normalized["criticality"] = (
        normalized["criticality"].fillna("").astype(str).str.strip().str.upper()
    ).replace(CRITICALITY_ALIASES)
    for row_index, value in normalized["criticality"].items():
        if value not in CRITICALITY_LEVELS:
            errors.append(
                f"第 {row_index + 2} 行的 criticality 无效：{value or '空值'}。"
            )

    parsed_backup = normalized["backup_supplier_available"].map(_parse_boolean)
    for row_index in normalized.index[parsed_backup.isna()]:
        errors.append(
            f"第 {row_index + 2} 行的 backup_supplier_available 必须为 True/False、"
            "是/否或 1/0。"
        )
    normalized["backup_supplier_available"] = parsed_backup
    normalized["backup_supplier"] = normalized["backup_supplier"].apply(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    missing_backup_name = (
        normalized["backup_supplier_available"].eq(True)
        & normalized["backup_supplier"].eq("")
    )
    for row_index in normalized.index[missing_backup_name]:
        errors.append(
            f"第 {row_index + 2} 行标记了备用供应商可用，但 backup_supplier 为空。"
        )

    if errors:
        return None, errors
    return normalized.reset_index(drop=True), []


def _row_to_part(row: pd.Series) -> dict[str, Any]:
    part = row.to_dict()
    part["backup_supplier"] = part["backup_supplier"] or None
    part["scenario"] = "Batch Import"
    return part


def _summary_row(part: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    metrics = result["inventory_metrics"]
    risk = result["supplier_risk"]
    decision = result["replenishment_decision"]
    days = float(metrics["days_of_stock"])
    return {
        "part_code": part["part_code"],
        "part_name": part["part_name"],
        "supplier": part["supplier"],
        "current_stock": float(part["current_stock"]),
        "daily_usage": float(part["daily_usage"]),
        "lead_time_days": float(part["lead_time_days"]),
        "days_of_stock": "无消耗" if math.isinf(days) else round(days, 2),
        "stockout_gap": round(float(metrics["stockout_gap"]), 2),
        "risk_level": risk["risk_level"],
        "recommended_action": decision["recommended_action"],
        "recommended_order_qty": decision["recommended_order_qty"],
        "analysis_status": "SUCCESS",
        "error": "",
    }


def analyze_batch(
    frame: pd.DataFrame,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Run the existing four-node graph once per row with failure isolation."""

    normalized, errors = validate_batch_dataframe(frame)
    if errors or normalized is None:
        raise ValueError("\n".join(errors))

    graph = build_supply_chain_graph()
    details: dict[str, dict[str, Any]] = {}
    summary_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    total = len(normalized)

    for position, (_, row) in enumerate(normalized.iterrows(), start=1):
        part = _row_to_part(row)
        part_code = str(part["part_code"])
        try:
            state = create_initial_state("Batch Import", part, use_llm_report=False)
            result = graph.invoke(state)
            if result.get("workflow_error"):
                raise RuntimeError(result["workflow_error"])
            details[part_code] = result
            summary_rows.append(_summary_row(part, result))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failures.append({"part_code": part_code, "error": error})
            summary_rows.append(
                {
                    "part_code": part_code,
                    "part_name": part["part_name"],
                    "supplier": part["supplier"],
                    "current_stock": part["current_stock"],
                    "daily_usage": part["daily_usage"],
                    "lead_time_days": part["lead_time_days"],
                    "days_of_stock": "",
                    "stockout_gap": "",
                    "risk_level": "",
                    "recommended_action": "",
                    "recommended_order_qty": "",
                    "analysis_status": "FAILED",
                    "error": error,
                }
            )
        if progress_callback:
            progress_callback(position, total)

    summary = pd.DataFrame(summary_rows)
    risk_rank = summary["risk_level"].map({"HIGH": 0, "MEDIUM": 1, "LOW": 2})
    summary = (
        summary.assign(
            _status_rank=summary["analysis_status"].map({"SUCCESS": 0, "FAILED": 1}),
            _risk_rank=risk_rank.fillna(3),
            _gap_rank=pd.to_numeric(summary["stockout_gap"], errors="coerce").fillna(-1),
        )
        .sort_values(
            ["_status_rank", "_risk_rank", "_gap_rank", "part_code"],
            ascending=[True, True, False, True],
            kind="stable",
        )
        .drop(columns=["_status_rank", "_risk_rank", "_gap_rank"])
        .reset_index(drop=True)
    )
    return {
        "summary": summary,
        "details": details,
        "failures": failures,
        "success_count": len(details),
        "failure_count": len(failures),
        "total_count": total,
    }


def batch_results_csv_bytes(batch_result: dict[str, Any]) -> bytes:
    return batch_result["summary"].to_csv(index=False).encode("utf-8-sig")
