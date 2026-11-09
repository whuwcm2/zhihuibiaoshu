from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
ARCH_PATH = ROOT / "系统架构图.png"
PPT_PATH = ROOT / "产品设计与技术架构.pptx"

FONT = "Microsoft YaHei"
FONT_BOLD = "Microsoft YaHei"
FONT_FILE = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD_FILE = r"C:\Windows\Fonts\msyhbd.ttc"

NAVY = "#0B1B33"
NAVY_SOFT = "#102A43"
INK = "#132238"
MUTED = "#5B6B82"
LINE = "#DCE6F2"
WHITE = "#FFFFFF"
BLUE = "#2563EB"
BLUE_DARK = "#0B3B8C"
BLUE_LIGHT = "#EAF2FF"
GREEN = "#0F766E"
GREEN_LIGHT = "#E9F9F2"
AMBER = "#B45309"
AMBER_LIGHT = "#FFF6E6"
PURPLE = "#6D28D9"
PURPLE_LIGHT = "#F4EDFF"
PINK = "#BE185D"
PINK_LIGHT = "#FFF0F5"
TEAL = "#0E7490"
TEAL_LIGHT = "#E6F7FA"


def C(value: str) -> RGBColor:
    value = value.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


# ---------------------------------------------------------------------------
# Architecture image
# ---------------------------------------------------------------------------

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD_FILE if bold else FONT_FILE, size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text).split("\n"):
        if not raw_line:
            lines.append("")
            continue
        current = ""
        for char in raw_line:
            candidate = current + char
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines


def _text_block(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 6,
) -> int:
    x, y = xy
    lines = _wrap(draw, text, font, max_width)
    line_height = draw.textbbox((0, 0), "国Ag", font=font)[3] + line_gap
    for index, line in enumerate(lines):
        draw.text((x, y + index * line_height), line, font=font, fill=fill)
    return y + len(lines) * line_height


def _pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fill: str,
    fg: str,
    font: ImageFont.FreeTypeFont,
    padding_x: int = 16,
    height: int = 36,
) -> int:
    x, y = xy
    width = int(draw.textlength(text, font=font)) + padding_x * 2
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=fill)
    draw.text((x + padding_x, y + (height - draw.textbbox((0, 0), text, font=font)[3]) // 2 - 2), text, font=font, fill=fg)
    return width


def _card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    subtitle: str,
    fill: str,
    border: str,
    title_color: str,
    subtitle_color: str,
    accent: str,
    tag: str | None = None,
    title_size: int = 30,
    subtitle_size: int = 21,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1, y1 + 7, x2, y2 + 7), radius=20, fill="#E3EBF6")
    draw.rounded_rectangle(box, radius=20, fill=fill, outline=border, width=2)
    draw.rounded_rectangle((x1, y1 + 16, x1 + 7, y2 - 16), radius=4, fill=accent)
    title_font = _font(title_size, True)
    subtitle_font = _font(subtitle_size, False)
    title_x = x1 + 26
    title_width = x2 - x1 - 52
    if tag:
        tag_font = _font(15, True)
        tag_w = int(draw.textlength(tag, font=tag_font)) + 20
        draw.rounded_rectangle((x2 - tag_w - 18, y1 + 16, x2 - 18, y1 + 46), radius=15, fill="#FFF4DE", outline="#F4C36A")
        draw.text((x2 - tag_w - 8, y1 + 21), tag, font=tag_font, fill=AMBER)
        title_width -= tag_w + 8
    title_bottom = _text_block(draw, (title_x, y1 + 20), title, title_font, title_color, title_width, 4)
    _text_block(draw, (title_x, title_bottom + 6), subtitle, subtitle_font, subtitle_color, x2 - title_x - 26, 3)


def build_architecture_image(path: Path) -> None:
    width, height = 2560, 1440
    image = Image.new("RGB", (width, height), "#F7FAFF")
    draw = ImageDraw.Draw(image)

    # Soft vertical gradient background.
    top = (248, 251, 255)
    bottom = (235, 242, 252)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)

    # Header.
    draw.rounded_rectangle((100, 72, 270, 112), radius=20, fill="#E8F1FF", outline="#B9D2FA")
    draw.text((120, 80), "SYSTEM ARCHITECTURE", font=_font(18, True), fill=BLUE_DARK)
    draw.text((100, 128), "zhibiao 系统架构", font=_font(78, True), fill=NAVY)
    draw.text((104, 218), "从招标文件知识到可审核投标文件的全链路", font=_font(30), fill=MUTED)
    draw.line((100, 258, 2460, 258), fill="#D7E3F3", width=2)

    badges = [
        ("FastAPI + Celery", "#E8F5E9", "#2E7D32"),
        ("LangGraph + RAG", "#F3E5F5", "#6D28D9"),
        ("PostgreSQL + Chroma", "#E0F7FA", "#0E7490"),
    ]
    badge_y = 76
    for label, fill, fg in badges:
        tag_font = _font(18, True)
        tag_w = int(draw.textlength(label, font=tag_font)) + 34
        draw.rounded_rectangle((2460 - tag_w, badge_y, 2460, badge_y + 38), radius=19, fill=fill, outline=fg)
        draw.text((2460 - tag_w + 17, badge_y + 9), label, font=tag_font, fill=fg)
        badge_y += 48

    layer_defs = [
        ("01", "交互层", BLUE, "#EAF3FF", 282, 132, [
            ("React 工作台", "上传 / 编写 / 文档库 / 历史产物", None),
            ("Electron 桌面端", "本地预览 / 打开文件夹 / 文件定位", None),
            ("任务与结果视图", "阶段进度 / 评分报告 / 审查问题", None),
        ]),
        ("02", "接入层", "#2E7D32", "#F1FBF6", 446, 132, [
            ("FastAPI REST API", "parse / search / bids / companies", None),
            ("Pydantic 校验", "请求模型 / 响应模型 / 错误码", None),
            ("文件与轮询接口", "下载 / 预览 / 任务状态查询", None),
        ]),
        ("03", "异步任务层", "#B45309", "#FFF9EF", 610, 132, [
            ("Redis Broker", "任务队列 / 结果后端", None),
            ("Celery Worker", "解析 / 抽取 / 投标生成", None),
            ("tasks 表", "状态 / 阶段 / 重试 / 耗时", None),
        ]),
        ("04", "知识与检索层", "#6D28D9", "#F8F3FF", 774, 190, [
            ("MinerU / PyMuPDF", "精准解析 + PyMuPDF 兜底", "外部"),
            ("content_list + 分块", "页码 / 标题 / 表格 table_id", None),
            ("智谱 Embedding", "embedding-3 / 批量向量", "外部"),
            ("Chroma + 混合检索", "BM25 多路 + 向量 + RRF", None),
        ]),
        ("05", "生成与可观测层", "#BE185D", "#FFF4F8", 994, 145, [
            ("LangGraph Agents", "Planner → Writers → Reviewer", None),
            ("DeepSeek LLM", "技术 / 商务 / 格式分批写作", "外部"),
            ("Prompt Hub + LangSmith", "提示词版本化 / Trace", "外部"),
            ("规则审计", "评分覆盖 / 占位符 / 公司名", None),
        ]),
        ("06", "数据与基础设施", "#0E7490", "#F0FAFA", 1169, 140, [
            ("PostgreSQL", "users / projects / documents / tasks / companies", None),
            ("Alembic", "schema 版本管理", None),
            ("MCP（只读）", "Claude Code 数据库访问", "只读"),
        ]),
    ]

    card_area_x1 = 330
    card_area_x2 = 2470
    for index, (number, name, color, light, y, h, cards) in enumerate(layer_defs):
        draw.rounded_rectangle((84, y - 10, 2478, y + h + 10), radius=26, fill=light)
        draw.rounded_rectangle((100, y + 18, 300, y + h - 18), radius=18, fill=color)
        draw.text((120, y + 30), number, font=_font(23, True), fill="#FFFFFF")
        name_font = _font(21, True)
        name_lines = _wrap(draw, name, name_font, 160)
        name_top = y + 58
        for line_index, line in enumerate(name_lines):
            draw.text((120, name_top + line_index * 28), line, font=name_font, fill="#FFFFFF")

        count = len(cards)
        gap = 26
        card_width = int((card_area_x2 - card_area_x1 - gap * (count - 1)) / count)
        card_y1 = y + 20
        card_y2 = y + h - 20
        for card_index, (title, subtitle, tag) in enumerate(cards):
            x1 = card_area_x1 + card_index * (card_width + gap)
            x2 = x1 + card_width
            title_size = 25 if count >= 5 else (27 if count == 4 else 30)
            subtitle_size = 18 if count >= 5 else (19 if count == 4 else 21)
            _card(
                draw,
                (x1, card_y1, x2, card_y2),
                title,
                subtitle,
                "#FFFFFF" if count >= 5 else "#FCFDFF",
                "#D8E4F5",
                color,
                MUTED,
                color,
                tag,
                title_size,
                subtitle_size,
            )

    # Vertical main-flow arrows between layers.
    arrow_x = 1375
    arrow_font = _font(18, True)
    arrows = [
        (414, 444, "HTTP / 轮询"),
        (578, 608, "Celery 投递"),
        (742, 772, "解析 / 抽取"),
        (964, 992, "检索 / 生成"),
        (1139, 1167, "状态 / 结果写回"),
    ]
    for y1, y2, label in arrows:
        draw.line((arrow_x, y1, arrow_x, y2 - 12), fill="#64748B", width=4)
        draw.polygon([(arrow_x, y2), (arrow_x - 10, y2 - 14), (arrow_x + 10, y2 - 14)], fill="#64748B")
        label_w = int(draw.textlength(label, font=arrow_font)) + 24
        draw.rounded_rectangle((arrow_x + 18, (y1 + y2) // 2 - 16, arrow_x + 18 + label_w, (y1 + y2) // 2 + 14), radius=14, fill="#FFFFFF", outline="#D7E3F3")
        draw.text((arrow_x + 30, (y1 + y2) // 2 - 9), label, font=arrow_font, fill="#475569")

    # Footer legend.
    draw.line((100, 1338, 2460, 1338), fill="#D7E3F3", width=2)
    draw.text((100, 1356), "颜色区分层级 · 圆角矩形为组件 · 标签表示外部服务 / 只读能力", font=_font(19), fill=MUTED)
    legend = [
        ("交互", BLUE), ("接入", "#2E7D32"), ("任务", "#B45309"),
        ("知识", "#6D28D9"), ("生成", "#BE185D"), ("数据", "#0E7490"),
    ]
    x = 1450
    for label, color in legend:
        draw.rounded_rectangle((x, 1360, x + 18, 1378), radius=5, fill=color)
        draw.text((x + 26, 1358), label, font=_font(18), fill=MUTED)
        x += 118
    draw.text((2178, 1356), "zhibiao · 2026.11", font=_font(19, True), fill=NAVY)

    image.save(path, "PNG")


# ---------------------------------------------------------------------------
# PPT helpers
# ---------------------------------------------------------------------------

def _style_run(run, size: float, color: str, bold: bool = False) -> None:
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = C(color)
    r_pr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        element = r_pr.find(qn(tag))
        if element is None:
            element = etree.SubElement(r_pr, qn(tag))
        element.set("typeface", FONT_BOLD if bold else FONT)


def add_text(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    size: float = 16,
    color: str = INK,
    bold: bool = False,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    line_spacing: float = 1.1,
    margin: float = 0.02,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = Inches(margin)
    frame.margin_bottom = Inches(margin)
    for index, line in enumerate(str(text).split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.line_spacing = line_spacing
        paragraph.space_after = Pt(2)
        run = paragraph.add_run()
        run.text = line
        _style_run(run, size, color, bold)
    return box


def add_shape(
    slide,
    shape_type,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str,
    line: str | None = None,
    radius: float | None = None,
):
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    try:
        shape.shadow.inherit = False
    except Exception:
        pass
    shape.fill.solid()
    shape.fill.fore_color.rgb = C(fill)
    if line:
        shape.line.color.rgb = C(line)
        shape.line.width = Pt(1.2)
    else:
        shape.line.fill.background()
    if radius is not None and shape_type == MSO_SHAPE.ROUNDED_RECTANGLE:
        shape.adjustments[0] = radius
    return shape


def add_card(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str,
    fill: str,
    border: str,
    title_color: str,
    body_color: str = MUTED,
    accent: str | None = None,
    title_size: float = 15,
    body_size: float = 10.5,
):
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill, border, 0.08)
    if accent:
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y + 0.14, 0.06, h - 0.28, accent, None, 0.5)
    title_x = x + (0.22 if not accent else 0.24)
    add_text(slide, title_x, y + 0.14, w - 0.42, 0.34, title, title_size, title_color, True)
    add_text(slide, title_x, y + 0.52, w - 0.42, h - 0.62, body, body_size, body_color, False, line_spacing=1.18)


def add_pill(slide, x: float, y: float, w: float, text: str, fill: str, color: str, size: float = 10):
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, 0.34, fill, None, 0.5)
    add_text(slide, x, y + 0.045, w, 0.24, text, size, color, True, PP_ALIGN.CENTER)


def add_arrow(slide, x: float, y: float, w: float = 0.24, h: float = 0.26, color: str = "#9AA9BD"):
    add_shape(slide, MSO_SHAPE.RIGHT_ARROW, x, y, w, h, color)


def add_header(slide, section: str, title: str, subtitle: str | None = None):
    add_text(slide, 0.72, 0.42, 6.5, 0.25, section, 10, BLUE, True)
    add_text(slide, 0.72, 0.74, 11.6, 0.52, title, 27, INK, True)
    if subtitle:
        add_text(slide, 0.74, 1.33, 11.6, 0.35, subtitle, 12, MUTED, False)
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.72, 1.79, 0.58, 0.05, BLUE, None, 0.5)
    footer(slide)


def footer(slide, page: int | None = None):
    add_shape(slide, MSO_SHAPE.RECTANGLE, 0.72, 7.01, 11.88, 0.012, LINE, None)
    add_text(slide, 0.72, 7.08, 7.5, 0.22, "zhibiao · 产品设计与技术架构", 8.5, MUTED)
    if page is not None:
        add_text(slide, 12.0, 7.08, 0.6, 0.22, f"{page:02d}", 8.5, MUTED, False, PP_ALIGN.RIGHT)


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def background(slide, color: str):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = C(color)


# ---------------------------------------------------------------------------
# Deck
# ---------------------------------------------------------------------------

def build_deck() -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # 01 Cover
    slide = blank(prs)
    background(slide, NAVY)
    add_shape(slide, MSO_SHAPE.OVAL, 10.2, -1.2, 4.4, 4.4, "#122B4A", None)
    add_shape(slide, MSO_SHAPE.OVAL, 11.8, 4.3, 3.1, 3.1, "#0F2A47", None)
    add_shape(slide, MSO_SHAPE.OVAL, -1.0, 5.5, 3.8, 3.8, "#0F2A47", None)
    add_pill(slide, 0.85, 0.8, 1.65, "zhibiao", "#2563EB", WHITE, 11)
    add_text(slide, 0.85, 1.55, 7.7, 0.65, "标书智能工作台", 42, WHITE, True)
    add_text(slide, 0.88, 2.35, 7.3, 0.55, "产品设计与技术架构", 25, "#C9D8EA", False)
    add_text(slide, 0.9, 3.15, 6.8, 0.9, "从招标文件解析，到可审核投标文件的全链路 AI 工作流", 15, "#9FB3CA", False)
    tags = [
        ("LangGraph 多 Agent", 0.9, 4.55, 2.1),
        ("混合检索 RAG", 3.1, 4.55, 1.7),
        ("FastAPI + Celery", 0.9, 5.0, 2.0),
        ("PostgreSQL + Chroma", 3.0, 5.0, 2.4),
    ]
    for text, x, y, w in tags:
        add_pill(slide, x, y, w, text, "#17365B", "#DCE9F8", 9.5)
    add_text(slide, 0.9, 6.75, 5.5, 0.25, "2026.11 · 内部产品交流材料", 9, "#7F96B0")

    # Cover right mini flow
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 8.25, 1.35, 4.35, 4.85, "#102A43", "#244A70", 0.05)
    add_text(slide, 8.58, 1.65, 3.7, 0.3, "一条可追溯的生成链路", 12, "#DCE9F8", True)
    mini_steps = [
        ("PDF 招标文件", "解析 / 抽取"),
        ("结构化知识库", "页码 / 章节 / 表格"),
        ("混合检索", "BM25 + 向量 + 意图"),
        ("多 Agent 写作", "技术 / 商务 / 格式"),
        ("审核与导出", "评分覆盖 / Word"),
    ]
    y = 2.15
    for i, (title, sub) in enumerate(mini_steps):
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 8.6, y, 3.6, 0.62, "#17365B", "#2C557D", 0.12)
        add_text(slide, 8.78, y + 0.1, 0.3, 0.25, f"{i + 1:02d}", 9, "#7FB5FF", True)
        add_text(slide, 9.15, y + 0.08, 1.4, 0.24, title, 10.5, WHITE, True)
        add_text(slide, 10.55, y + 0.1, 1.45, 0.22, sub, 7.5, "#9FB3CA")
        if i < len(mini_steps) - 1:
            add_shape(slide, MSO_SHAPE.DOWN_ARROW, 10.18, y + 0.67, 0.18, 0.14, "#3E6B96")
        y += 0.78

    # 02 Contents
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "CONTENTS", "今天讲什么", "产品洞察、用户体验、技术架构与落地路线")
    agenda = [
        ("01", "产品洞察", "为什么做、为谁做、标书制作的结构性矛盾", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("02", "用户体验", "四步工作流与功能地图，如何把能力交给用户", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("03", "技术架构", "知识入库、混合检索、多 Agent 与工程化", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
        ("04", "路线与边界", "从可用闭环走向规模化，以及产品不做什么", AMBER_LIGHT, "#FFD89A", "#8A4B00"),
    ]
    positions = [(0.8, 2.05), (6.75, 2.05), (0.8, 4.0), (6.75, 4.0)]
    for (number, title, body, fill, border, title_color), (x, y) in zip(agenda, positions):
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, 5.55, 1.55, fill, border, 0.08)
        add_text(slide, x + 0.25, y + 0.2, 0.65, 0.5, number, 18, title_color, True)
        add_text(slide, x + 0.92, y + 0.22, 4.2, 0.35, title, 16, title_color, True)
        add_text(slide, x + 0.92, y + 0.72, 4.25, 0.55, body, 10.5, MUTED)
    add_text(slide, 0.82, 6.28, 11.5, 0.45, "把标书编写，从“文档搬运”变成“知识工程”。", 16, BLUE_DARK, True)

    # 03 Problem
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "01 / 产品洞察", "标书制作的结构性矛盾", "信息密度、写作效率与合规要求同时上升")
    problems = [
        ("01", "读不完", "招标文件长、表格多、资格条款分散，关键信息难定位。", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("02", "写不完", "技术标、商务标、格式文件重复组织，章节和评分点容易漏。", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("03", "对不齐", "资格材料、格式要求与评分标准脱节，合规校对成本高。", AMBER_LIGHT, "#FFD89A", "#8A4B00"),
    ]
    for i, (number, title, body, fill, border, title_color) in enumerate(problems):
        x = 0.8 + i * 3.88
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.05, 3.62, 3.0, fill, border, 0.08)
        add_text(slide, x + 0.25, 2.28, 0.65, 0.45, number, 16, title_color, True)
        add_text(slide, x + 0.25, 2.82, 2.8, 0.45, title, 23, title_color, True)
        add_text(slide, x + 0.25, 3.48, 3.05, 1.1, body, 12, MUTED)
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.8, 5.55, 11.72, 0.78, NAVY, None, 0.08)
    add_text(slide, 1.08, 5.73, 11.15, 0.34, "真正的瓶颈不是“写”，而是知识提取、检索与合规校验没有形成闭环。", 13, WHITE, True)

    # 04 Positioning
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "01 / 产品洞察", "产品定位：可审核的标书智能工作台", "不是代写工具，而是把招标知识、投标资料与写作流程连接起来")
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.8, 2.02, 4.45, 3.52, NAVY, None, 0.06)
    add_text(slide, 1.1, 2.35, 3.8, 0.35, "PRODUCT THESIS", 9, "#7FB5FF", True)
    add_text(slide, 1.1, 2.85, 3.8, 1.35, "把标书编写\n变成知识工程", 28, WHITE, True, line_spacing=1.15)
    add_text(slide, 1.1, 4.35, 3.75, 0.75, "知识、检索、生成、审核在同一条链路上闭环。", 11.5, "#C9D8EA")
    values = [
        ("知识化", "PDF → 页级 / 章节级知识块，表格独立成块。", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("可检索", "BM25 + 向量 + 意图路由，资格材料强制召回。", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
        ("可生成", "LangGraph 多 Agent 分工写作，Markdown / Word 双产物。", PINK_LIGHT, "#FFC2D6", "#8A1F4A"),
        ("可审核", "页码溯源、规则审计、评分覆盖报告。", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
    ]
    positions = [(5.65, 2.02), (8.9, 2.02), (5.65, 3.78), (8.9, 3.78)]
    for (title, body, fill, border, title_color), (x, y) in zip(values, positions):
        add_card(slide, x, y, 3.05, 1.55, title, body, fill, border, title_color, MUTED, title_size=15, body_size=9.8)
    for i, text in enumerate(["不编造", "可追溯", "可编辑", "可异步"]):
        add_pill(slide, 0.82 + i * 2.86, 6.0, 1.55, text, "#EAF2FF", BLUE_DARK, 10)

    # 05 User journey
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "02 / 用户体验", "四步工作流：从 PDF 到可提交文档", "把复杂能力收进一个清晰、可恢复的工作台")
    steps = [
        ("01", "上传招标文件", "PDF 上传\nMinerU / PyMuPDF\n结构化抽取", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("02", "选择公司资料", "公司库 / 表单\n高级 JSON\n缺失字段占位", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("03", "生成投标文件", "技术 / 商务 / 格式\n分批生成\n实时阶段进度", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
        ("04", "审核与导出", "评分覆盖 / 审查问题\nMarkdown 预览\nWord 下载", AMBER_LIGHT, "#FFD89A", "#8A4B00"),
    ]
    x_positions = [0.7, 3.52, 6.34, 9.16]
    for i, ((number, title, body, fill, border, title_color), x) in enumerate(zip(steps, x_positions)):
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.08, 2.62, 3.12, fill, border, 0.08)
        add_text(slide, x + 0.2, 2.28, 0.5, 0.35, number, 13, title_color, True)
        add_text(slide, x + 0.2, 2.7, 2.2, 0.58, title, 14.5, title_color, True)
        add_text(slide, x + 0.2, 3.42, 2.2, 1.3, body, 10.2, MUTED, line_spacing=1.25)
        if i < 3:
            add_arrow(slide, x + 2.69, 3.45, 0.22, 0.24, "#A9B8CA")
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.7, 5.65, 11.85, 0.75, "#EAF2FF", "#C8DBF7", 0.08)
    add_text(slide, 0.98, 5.83, 11.3, 0.3, "任务状态统一写入 PostgreSQL：可轮询、可恢复、可审计；前端只负责呈现。", 11.5, BLUE_DARK, True)

    # 06 Feature map
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "02 / 用户体验", "功能地图：一条主链路，两类资产", "知识资产 + 公司资产，共同驱动可审核生成")
    panels = [
        ("输入与知识", BLUE_LIGHT, "#BBD4FF", BLUE_DARK, ["上传与解析", "结构化抽取", "已解析文档库", "公司信息库"]),
        ("检索与生成", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A", ["混合检索", "多 Agent 写作", "第八章格式文件", "Markdown / Word 导出"]),
        ("治理与运营", GREEN_LIGHT, "#B7E8D5", "#0F6B4F", ["任务历史", "合规审查", "评分覆盖报告", "LangSmith / MCP"]),
    ]
    for i, (title, fill, border, title_color, items) in enumerate(panels):
        x = 0.75 + i * 3.85
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.02, 3.55, 4.18, fill, border, 0.07)
        add_text(slide, x + 0.25, 2.28, 3.0, 0.35, title, 16, title_color, True)
        for j, item in enumerate(items):
            cy = 2.9 + j * 0.62
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x + 0.22, cy, 3.08, 0.46, "#FFFFFF", border, 0.2)
            add_text(slide, x + 0.42, cy + 0.11, 2.7, 0.25, f"•  {item}", 10.2, title_color, False)
    add_text(slide, 0.78, 6.35, 11.6, 0.3, "一条主链路：PDF → 知识 → 检索 → 标书 → 审核", 11.5, MUTED)

    # 07 Architecture image
    slide = blank(prs)
    background(slide, "#F8FBFF")
    slide.shapes.add_picture(str(ARCH_PATH), Inches(0.52), Inches(0.16), width=Inches(12.3))

    # 08 Ingestion
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "03 / 技术架构", "知识入库：把非结构化 PDF 变成可检索资产", "解析、分块、嵌入、入库，每一步都保留可追溯信息")
    steps = [
        ("01", "上传 / 分片", "超过 200 页\nPyMuPDF 本地分片"),
        ("02", "MinerU 解析", "精准解析为主\nPyMuPDF 兜底"),
        ("03", "content_list", "页码 / 标题\n表格 HTML"),
        ("04", "章节感知分块", "表格独立成块\ntable_id / tags"),
        ("05", "Embedding", "智谱 embedding-3\n写入 Chroma"),
    ]
    xs = [0.75, 3.11, 5.47, 7.83, 10.19]
    for i, ((number, title, body), x) in enumerate(zip(steps, xs)):
        fill = [BLUE_LIGHT, PURPLE_LIGHT, PINK_LIGHT, AMBER_LIGHT, GREEN_LIGHT][i]
        border = ["#BBD4FF", "#D8C2FF", "#FFC2D6", "#FFD89A", "#B7E8D5"][i]
        title_color = [BLUE_DARK, "#4B2A8A", "#8A1F4A", "#8A4B00", "#0F6B4F"][i]
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.08, 2.05, 1.95, fill, border, 0.08)
        add_text(slide, x + 0.18, 2.24, 0.4, 0.28, number, 10, title_color, True)
        add_text(slide, x + 0.18, 2.58, 1.7, 0.45, title, 12, title_color, True)
        add_text(slide, x + 0.18, 3.13, 1.7, 0.7, body, 9.0, MUTED, line_spacing=1.2)
        if i < 4:
            add_arrow(slide, x + 2.08, 2.92, 0.22, 0.24, "#A9B8CA")
    design = [
        ("表格独立成块", "表格不参与正文合并，避免 table_id 丢失。", PINK_LIGHT, "#FFC2D6", "#8A1F4A"),
        ("元数据可追溯", "页码、章节、type、table_id、tags 全部写入。", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
        ("缓存与幂等", "data/parsed 缓存，doc_id 先删后写。", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
    ]
    for i, (title, body, fill, border, title_color) in enumerate(design):
        x = 0.75 + i * 3.9
        add_card(slide, x, 4.55, 3.65, 1.55, title, body, fill, border, title_color, MUTED, title_size=13, body_size=9.8)

    # 09 Retrieval
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "03 / 技术架构", "检索：关键词优先，向量补充，意图路由", "不是“只做向量”，而是让表格、标题、资格材料各有通道")
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.75, 2.02, 7.25, 3.75, "#FFFFFF", "#D9E5F3", 0.05)
    add_pill(slide, 1.0, 2.24, 1.55, "用户问题", "#EAF2FF", BLUE_DARK, 10)
    add_arrow(slide, 2.65, 2.28, 0.22, 0.24, "#A9B8CA")
    add_pill(slide, 2.98, 2.24, 1.95, "意图识别", PURPLE_LIGHT, "#4B2A8A", 10)
    add_arrow(slide, 5.02, 2.28, 0.22, 0.24, "#A9B8CA")
    add_pill(slide, 5.35, 2.24, 1.75, "权重路由", PINK_LIGHT, "#8A1F4A", 10)
    channels = [
        ("BM25 全局", 1.0, 3.08, BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("BM25 表格", 3.6, 3.08, PINK_LIGHT, "#FFC2D6", "#8A1F4A"),
        ("BM25 标题", 1.0, 3.72, GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("BM25 资格审查", 3.6, 3.72, AMBER_LIGHT, "#FFD89A", "#8A4B00"),
    ]
    for label, x, y, fill, border, title_color in channels:
        add_pill(slide, x, y, 2.1, label, fill, title_color, 9.5)
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 6.05, 3.02, 1.55, 1.45, PURPLE_LIGHT, "#D8C2FF", 0.12)
    add_text(slide, 6.17, 3.15, 1.3, 0.3, "向量", 11, "#4B2A8A", True)
    add_text(slide, 6.17, 3.5, 1.3, 0.75, "768 前缀\n余弦扫描", 8.8, MUTED)
    add_shape(slide, MSO_SHAPE.DOWN_ARROW, 6.68, 4.49, 0.22, 0.18, "#A9B8CA")
    add_shape(slide, MSO_SHAPE.DOWN_ARROW, 3.8, 4.43, 0.25, 0.2, "#A9B8CA")
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 1.0, 4.75, 6.6, 0.5, NAVY, None, 0.15)
    add_text(slide, 1.2, 4.86, 6.2, 0.25, "RRF 融合  →  归一化排序  →  Top-N", 10.5, WHITE, True)
    cards = [
        ("表格 / 条款", "关键词精确命中表格与章节标题。", PINK_LIGHT, "#FFC2D6", "#8A1F4A"),
        ("语义补充", "向量补充同义表达和上下文召回。", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("资格强制召回", "qualification 时至少一半结果来自资格块。", AMBER_LIGHT, "#FFD89A", "#8A4B00"),
    ]
    for i, (title, body, fill, border, title_color) in enumerate(cards):
        add_card(slide, 8.35, 2.02 + i * 1.28, 4.15, 1.1, title, body, fill, border, title_color, MUTED, title_size=12.5, body_size=9.2)
    add_text(slide, 0.78, 6.02, 11.65, 0.3, "BM25(k1=1.5, b=0.75)  +  Cosine  +  RRF(K=60)  ·  intent = formula / section_writing / qualification / general", 10.5, MUTED)

    # 10 Multi-agent
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "03 / 技术架构", "生成：LangGraph 多 Agent 协作", "规划、写作、审查、装配分工，批次可控、失败可恢复")
    agents = [
        ("Planner", "拆解评分因素\n与格式清单", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("Technical", "施工组织设计\n4 因素 / 批", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
        ("Commercial", "资格 + 商务\n8 条 / 批", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("Format", "第八章格式\n4 项 / 批", AMBER_LIGHT, "#FFD89A", "#8A4B00"),
        ("Reviewer", "结构审查\n规则审计", PINK_LIGHT, "#FFC2D6", "#8A1F4A"),
        ("Assembler", "合并 / 编号\n导出 Word", TEAL_LIGHT, "#B7E4EA", "#0E7490"),
    ]
    xs = [0.62 + i * 1.93 for i in range(6)]
    for i, ((title, body, fill, border, title_color), x) in enumerate(zip(agents, xs)):
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.05, 1.72, 1.08, fill, border, 0.1)
        add_text(slide, x + 0.12, 2.18, 1.5, 0.28, title, 10.5, title_color, True)
        add_text(slide, x + 0.12, 2.52, 1.45, 0.5, body, 8.2, MUTED, line_spacing=1.15)
        if i < 5:
            add_arrow(slide, x + 1.74, 2.46, 0.17, 0.2, "#A9B8CA")
    panels = [
        ("批次与稳定性", "技术 4 因素/批\n资格 8 条/批\n格式 4 项/批\n截断时递归二分", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("审查与质量", "Reviewer 只读标题/因素\n规则审计覆盖评分与资格\n占位符 / 未授权公司名检查", PINK_LIGHT, "#FFC2D6", "#8A1F4A"),
    ]
    for i, (title, body, fill, border, title_color) in enumerate(panels):
        x = 0.75 + i * 6.02
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 3.55, 5.8, 2.05, fill, border, 0.06)
        add_text(slide, x + 0.25, 3.75, 4.8, 0.3, title, 14, title_color, True)
        add_text(slide, x + 0.25, 4.18, 5.2, 1.1, body, 10.2, MUTED, line_spacing=1.25)
    add_text(slide, 0.8, 6.0, 11.6, 0.3, "Prompt Hub 版本化提示词  ·  LangSmith 上报 LangGraph 节点与 LLM 调用", 10.5, MUTED)

    # 11 Quality
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "03 / 技术架构", "可信生成：每一条结论都能回到原文", "让“生成”进入可核对、可审计、可人工终审的状态")
    guards = [
        ("事实边界", "只使用招标文件事实和投标人资料；缺失信息统一写【待填写】，不编造公司、业绩、人员、金额。", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("页码溯源", "抽取项保留 page 与 quote；核对页码存在性和原文子串，输出 provenance_warnings。", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("规则审计", "检查技术评分点、资格类别、格式项覆盖；检查占位符与未授权公司名称。", AMBER_LIGHT, "#FFD89A", "#8A4B00"),
        ("评分覆盖", "技术评分因素逐项匹配正文，计算 covered_points / total_points 与覆盖率。", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
    ]
    positions = [(0.75, 2.02), (6.6, 2.02), (0.75, 4.0), (6.6, 4.0)]
    for (title, body, fill, border, title_color), (x, y) in zip(guards, positions):
        add_card(slide, x, y, 5.6, 1.68, title, body, fill, border, title_color, MUTED, title_size=14.5, body_size=10)
    add_text(slide, 0.78, 6.02, 11.6, 0.3, "系统负责“发现风险”，投标人负责“确认事实”；人工终审仍是最后一环。", 11, MUTED)

    # 12 Engineering
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "03 / 技术架构", "工程化：异步、持久化、可观测", "长任务不阻塞请求，状态和结果可恢复、可追踪")
    rows = [
        ("01", "异步任务", "Redis + Celery 执行解析、抽取和投标生成；FastAPI 立即返回 job_id。", BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("02", "持久化", "PostgreSQL 保存 users / projects / documents / tasks / companies；Alembic 管理 schema。", GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("03", "可观测", "LangSmith 追踪 LangGraph 节点、LLM 调用与检索；Prompt Hub 管理提示词版本。", PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
    ]
    for i, (number, title, body, fill, border, title_color) in enumerate(rows):
        y = 2.02 + i * 1.22
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.75, y, 7.35, 1.02, fill, border, 0.08)
        add_text(slide, 0.98, y + 0.16, 0.45, 0.3, number, 10, title_color, True)
        add_text(slide, 1.5, y + 0.15, 1.5, 0.3, title, 13, title_color, True)
        add_text(slide, 3.0, y + 0.2, 4.8, 0.6, body, 9.5, MUTED, line_spacing=1.18)
    stats = [
        ("210", "页", "招标文件已跑通"),
        ("510", "个", "知识片段"),
        ("117", "个", "自动化测试"),
        ("~0.5", "s", "预热后检索"),
    ]
    for i, (number, unit, label) in enumerate(stats):
        x = 8.45 + (i % 2) * 2.05
        y = 2.02 + (i // 2) * 1.48
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, 1.85, 1.25, "#FFFFFF", "#D9E5F3", 0.1)
        add_text(slide, x + 0.14, y + 0.14, 1.55, 0.42, number, 22, BLUE_DARK, True)
        add_text(slide, x + 1.35, y + 0.3, 0.35, 0.2, unit, 8, MUTED)
        add_text(slide, x + 0.14, y + 0.76, 1.55, 0.25, label, 7.8, MUTED)
    add_text(slide, 8.45, 5.0, 4.0, 0.25, "当前工程验证，不代表商业指标", 8, MUTED)
    chips = ["FastAPI", "Redis", "Celery", "PostgreSQL", "Chroma", "Alembic", "LangSmith"]
    chip_colors = [BLUE_LIGHT, "#FFF3E0", "#FFF3E0", GREEN_LIGHT, PURPLE_LIGHT, "#E0F7FA", "#FCE4EC"]
    for i, chip in enumerate(chips):
        add_pill(slide, 0.8 + i * 1.55, 5.55, 1.42, chip, chip_colors[i], INK, 8.2)
    add_text(slide, 0.8, 6.0, 11.6, 0.25, "解析、检索、生成、持久化、追踪，全部落在同一条工程链路上。", 9.5, MUTED)

    # 13 Roadmap
    slide = blank(prs)
    background(slide, "#F8FBFF")
    add_header(slide, "04 / 路线与边界", "路线图：从可用到规模化", "先把闭环跑通，再把体验、治理和规模化补齐")
    phases = [
        ("NOW", "可用闭环", ["解析 / 抽取 / 检索", "多 Agent 标书生成", "评分覆盖与审查", "公司库与任务历史"], BLUE_LIGHT, "#BBD4FF", BLUE_DARK),
        ("NEXT", "体验与治理", ["账号、项目与权限", "模板库与修订留痕", "检索评测集", "更多招标文件适配"], GREEN_LIGHT, "#B7E8D5", "#0F6B4F"),
        ("LATER", "规模化", ["多租户 / 私有化", "指标看板", "模型路由与成本优化", "行业模板生态"], PURPLE_LIGHT, "#D8C2FF", "#4B2A8A"),
    ]
    for i, (phase, title, items, fill, border, title_color) in enumerate(phases):
        x = 0.75 + i * 3.85
        add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.05, 3.55, 3.55, fill, border, 0.06)
        add_pill(slide, x + 0.22, 2.25, 0.85, phase, "#FFFFFF", title_color, 8.5)
        add_text(slide, x + 0.24, 2.76, 2.9, 0.35, title, 16, title_color, True)
        for j, item in enumerate(items):
            add_text(slide, x + 0.24, 3.25 + j * 0.48, 2.95, 0.32, f"•  {item}", 9.8, MUTED)
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.78, 5.95, 11.6, 0.66, NAVY, None, 0.08)
    add_text(slide, 1.02, 6.1, 11.15, 0.3, "产品边界：不替投标人做事实承诺，不绕过人工终审。", 11, WHITE, True)

    # 14 Closing
    slide = blank(prs)
    background(slide, NAVY)
    add_shape(slide, MSO_SHAPE.OVAL, 10.0, -1.0, 4.0, 4.0, "#122B4A", None)
    add_shape(slide, MSO_SHAPE.OVAL, 11.8, 4.4, 3.0, 3.0, "#0F2A47", None)
    add_text(slide, 0.9, 1.55, 8.6, 1.9, "让标书编写\n从文档搬运，变成知识工程。", 38, WHITE, True, line_spacing=1.12)
    add_text(slide, 0.93, 4.2, 7.0, 0.35, "zhibiao · 标书智能工作台", 13, "#C9D8EA")
    chips = ["知识入库", "混合检索", "多 Agent 生成", "可审核交付"]
    for i, chip in enumerate(chips):
        add_pill(slide, 0.9 + i * 1.78, 5.0, 1.6, chip, "#17365B", "#DCE9F8", 9.2)
    add_text(slide, 0.92, 6.75, 5.0, 0.25, "2026.11", 9, "#7F96B0")
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 9.9, 1.55, 2.6, 4.1, "#102A43", "#244A70", 0.08)
    add_text(slide, 10.15, 1.85, 2.1, 0.3, "PDF", 18, "#7FB5FF", True)
    add_shape(slide, MSO_SHAPE.DOWN_ARROW, 11.1, 2.3, 0.2, 0.5, "#3E6B96")
    add_text(slide, 10.15, 2.95, 2.1, 0.3, "知识库", 18, "#7FB5FF", True)
    add_shape(slide, MSO_SHAPE.DOWN_ARROW, 11.1, 3.4, 0.2, 0.5, "#3E6B96")
    add_text(slide, 10.15, 4.05, 2.1, 0.3, "标书", 18, "#7FB5FF", True)
    add_text(slide, 10.15, 4.75, 2.0, 0.35, "可审核、可追溯", 9, "#9FB3CA")

    prs.save(PPT_PATH)


if __name__ == "__main__":
    build_architecture_image(ARCH_PATH)
    build_deck()
    print(f"architecture: {ARCH_PATH}")
    print(f"deck: {PPT_PATH}")
