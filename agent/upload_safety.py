"""Bound in-memory CSV/XLSX parsing before handing data to pandas."""
from __future__ import annotations

import io
from zipfile import BadZipFile, ZipFile

MAX_UPLOAD_BYTES = 5_000_000
MAX_UNCOMPRESSED_BYTES = 25_000_000
MAX_ARCHIVE_FILES = 200
MAX_COLUMNS = 40
MAX_TEXT_LENGTH = 500
PLANNING_ROW_LIMITS = {"settings": 1, "parts": 50, "suppliers": 100,
                       "demands": 4500, "orders": 500}


def validate_upload(content: bytes, *, xlsx: bool) -> None:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("上传文件不能为空，且不得超过 5 MB。")
    if not xlsx:
        if b"\x00" in content:
            raise ValueError("CSV 必须为文本文件。")
        return
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (len(entries) > MAX_ARCHIVE_FILES
                    or sum(e.file_size for e in entries) > MAX_UNCOMPRESSED_BYTES):
                raise ValueError("Excel 解压后体积或内部文件数量超出限制。")
            names = [e.filename.lower() for e in entries]
            if "[content_types].xml" not in names or "xl/workbook.xml" not in names:
                raise ValueError("文件不是有效的 XLSX 工作簿。")
            if any("vbaproject" in n or n.startswith("xl/externallinks/") for n in names):
                raise ValueError("演示环境不接受宏或外部链接工作簿。")
            if any(e.flag_bits & 1 for e in entries):
                raise ValueError("不支持加密工作簿。")
    except BadZipFile as exc:
        raise ValueError("Excel 文件损坏或格式不正确。") from exc


def validate_frame_size(frame, max_rows: int) -> None:
    if len(frame) > max_rows or len(frame.columns) > MAX_COLUMNS:
        raise ValueError(f"表格规模超出限制：最多 {max_rows} 行、{MAX_COLUMNS} 列。")
    if frame.map(lambda value: isinstance(value, str) and len(value) > MAX_TEXT_LENGTH).any().any():
        raise ValueError(f"单元格文字不得超过 {MAX_TEXT_LENGTH} 个字符。")


def validate_worksheet_size(sheet, max_rows: int) -> None:
    if sheet.max_row is None or sheet.max_column is None:
        sheet.calculate_dimension(force=True)
    if sheet.max_row > max_rows + 1 or sheet.max_column > MAX_COLUMNS:
        raise ValueError(f"Excel 工作表最多 {max_rows} 行数据、{MAX_COLUMNS} 列。")
