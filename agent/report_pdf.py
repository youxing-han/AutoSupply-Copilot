"""PDF export for one verified AutoSupply workflow result."""

from __future__ import annotations

import io
from html import escape
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


PDF_FONT = "STSong-Light"


def _register_font() -> None:
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))


def _format_number(value: Any, suffix: str = "") -> str:
    number = float(value)
    if number == float("inf"):
        return "无消耗"
    if number.is_integer():
        return f"{int(number):,}{suffix}"
    return f"{number:,.2f}{suffix}"


def build_pdf_report(result: dict[str, Any]) -> bytes:
    """Create a Chinese PDF using only verified workflow state fields."""

    _register_font()
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="AutoSupply Copilot Supply Risk Report",
        author="AutoSupply Copilot",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ChineseTitle",
        parent=styles["Title"],
        fontName=PDF_FONT,
        fontSize=20,
        leading=27,
        textColor=colors.HexColor("#17211F"),
        alignment=TA_LEFT,
        spaceAfter=4 * mm,
    )
    body_style = ParagraphStyle(
        "ChineseBody",
        parent=styles["BodyText"],
        fontName=PDF_FONT,
        fontSize=10.5,
        leading=17,
        textColor=colors.HexColor("#34423E"),
        wordWrap="CJK",
    )
    label_style = ParagraphStyle(
        "ChineseLabel",
        parent=body_style,
        fontSize=9,
        textColor=colors.HexColor("#71807A"),
    )

    part = result["selected_part"]
    metrics = result["inventory_metrics"]
    risk = result["supplier_risk"]
    decision = result["replenishment_decision"]
    story = [
        Paragraph("AutoSupply Copilot 供应风险报告", title_style),
        Paragraph(
            escape(f"{part['part_code']} · {part['part_name']} · {result['scenario']}"),
            label_style,
        ),
        Spacer(1, 5 * mm),
    ]
    facts = [] if result.get('inventory_projection') else [
        ["库存覆盖", _format_number(metrics["days_of_stock"], " 天")],
        ["供应商交期", _format_number(part["lead_time_days"], " 天")],
        ["潜在覆盖缺口", _format_number(metrics["stockout_gap"], " 天")],
        ["风险等级", str(risk["risk_level"])],
        ["建议订货量", _format_number(decision["recommended_order_qty"], " 件")],
        ["主要行动", str(decision["recommended_action"])],
    ]
    if result.get("inventory_projection"):
        projection = result["inventory_projection"]
        facts = [
            ["模型", "time-phased-v2"],
            ["首次预计缺料", projection["first_shortage_date"] or "预测期内无缺料"],
            ["首次缺料量", f"{projection['first_shortage_quantity']} 件"],
            ["累计未满足需求", f"{projection['total_unmet_demand']} 件"],
            ["缺料日数", f"{projection['shortage_days']} 天"],
            ["期末可用库存", f"{projection['final_available']} 件"],
            ["风险等级", risk["risk_level"]],
            ["计划保障参考量", f"{decision['recommended_order_qty']} 件"],
        ]
    table = Table(facts, colWidths=[42 * mm, 105 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#71807A")),
                ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#17211F")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7F9F8")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E1E8E4")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E8EEEB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 7 * mm),
            Paragraph("管理层分析", title_style),
            Paragraph(
                escape(result["management_report"]).replace("\n", "<br/>"),
                body_style,
            ),
            Spacer(1, 6 * mm),
            Paragraph(
                "说明：本报告使用虚构模拟数据，不构成采购指令或真实生产承诺。",
                label_style,
            ),
        ]
    )
    document.build(story)
    return output.getvalue()
