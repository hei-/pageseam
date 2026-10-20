"""PaddleOCR（PP-StructureV3）封装：版面 + 表格 + 文字识别。

默认模型组合按 8 核 CPU、无 GPU 环境下的实测结果选定（每页约 3–6 秒，进程内存约 2.8GB），
可以用环境变量更换（config.OCR_MODELS），推理设备由 OCR_DEVICE 指定：
- 版面 PP-DocLayout-M、检测 PP-OCRv5_mobile_det、识别 PP-OCRv5_server_rec（中文准确度明显好于 mobile_rec）。
- 表格 SLANet_plus，先检测单元格再识别结构。端到端模式在宽表上会错位。
- 关闭表格方向分类：它会把宽而矮的表格误判为旋转过的表格，导致整张表被转置。
- OCR 前先做倾斜校正（deskew）：扫描表格倾斜 0.6° 就会单元格错位（值落到相邻的列）。
  不用 PaddleOCR 自带的 UVDoc 矫正：CPU 上慢，而且是非线性变形，坐标无法换算回原图。
- 默认的 PP-DocLayout_plus-L + 服务端检测模型组合，每页约 42 秒、内存 8GB，CPU 上不可用。
"""

from dataclasses import dataclass, field

import re
from html import escape
from html.parser import HTMLParser

import numpy as np
import pymupdf

from docparser import config

_engine = None


def engine():
    """每个工作进程加载一次。"""
    global _engine
    if _engine is None:
        from paddleocr import PPStructureV3

        _engine = PPStructureV3(
            layout_detection_model_name=config.OCR_MODELS["layout"],
            text_detection_model_name=config.OCR_MODELS["det"],
            text_recognition_model_name=config.OCR_MODELS["rec"],
            wired_table_structure_recognition_model_name=config.OCR_MODELS["table"],
            wireless_table_structure_recognition_model_name=config.OCR_MODELS["table"],
            use_doc_orientation_classify=True,  # 横着扫描、倒着扫描的页面先转正
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_region_detection=False,
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_seal_recognition=False,
            device=config.OCR_DEVICE,
            cpu_threads=config.OCR_THREADS,
        )
    return _engine


_recognizer = None


def recognizer():
    """单独的文字识别模型：补识别表格中检测模型漏掉的单元格（如单个数字、「—」）。"""
    global _recognizer
    if _recognizer is None:
        from paddleocr import TextRecognition

        _recognizer = TextRecognition(
            model_name=config.OCR_MODELS["rec"], device=config.OCR_DEVICE, cpu_threads=config.OCR_THREADS
        )
    return _recognizer


PREDICT_OPTIONS = {
    "use_e2e_wired_table_rec_model": False,
    "use_e2e_wireless_table_rec_model": False,
    "use_ocr_results_with_table_cells": True,
    "use_table_orientation_classify": False,
}


@dataclass
class Line:
    text: str
    score: float
    rect: pymupdf.Rect  # 页面显示坐标（与 page.rect 同一坐标系）
    angle: int  # 文字方向相对页面的旋转角度：0 / 90 / 180 / 270（逆时针）


@dataclass
class Block:
    label: str  # PP-StructureV3 的版面类别：doc_title、paragraph_title、text、table、image、seal……
    content: str  # 文字，表格为 HTML
    rect: pymupdf.Rect  # 页面显示坐标
    font_size: float = 0  # 估算的字号（磅）
    upright: pymupdf.Rect | None = None  # 转正后的坐标（磅，原点为识别区域左上角），生成 Word 时使用


@dataclass
class Result:
    lines: list[Line] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    angle: int = 0  # 页面被转正时旋转的角度
    skew: float = 0  # 倾斜校正的角度（度，逆时针为正）
    upright_size: tuple[float, float] = (0, 0)  # 转正后识别区域的宽高（磅）


def _to_bgr(pix: pymupdf.Pixmap) -> np.ndarray:
    if pix.alpha or pix.n != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix, 0)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
    return np.ascontiguousarray(img[:, :, ::-1])


def _unrotate(x: float, y: float, angle: int, w: int, h: int) -> tuple[float, float]:
    """把转正后图片中的点映射回原图。w、h 是转正后图片的宽高。"""
    if angle == 270:  # 原图是逆时针转了 90°
        return y, w - x
    if angle == 90:  # 原图是顺时针转了 90°
        return h - y, x
    if angle == 180:
        return w - x, h - y
    return x, y


def recognize(page: pymupdf.Page, clip: pymupdf.Rect | None = None, dpi: int | None = None) -> Result:
    """识别整页或页面中的一个区域（clip，页面显示坐标），返回的坐标都换算成页面显示坐标。"""
    dpi = dpi or config.OCR_DPI
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    bgr, skew, inverse, pad = deskew(_to_bgr(pix))
    out = engine().predict(bgr, **PREDICT_OPTIONS)[0]
    res = out.json["res"]

    angle = int((res.get("doc_preprocessor_res") or {}).get("angle") or 0)
    w, h = res["width"], res["height"]  # 转正后的尺寸
    scale = 72 / dpi
    ox, oy = (clip.x0, clip.y0) if clip else (0, 0)

    def to_page(box) -> pymupdf.Rect:
        x0, y0, x1, y1 = box
        pts = [_unrotate(x, y, angle, w, h) for x, y in ((x0, y0), (x1, y1))]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        rect = pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))
        if inverse is not None:  # 倾斜校正过：中心点换算回原图，宽高不变（文字层和原图上的文字对齐）
            cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
            nx, ny = inverse @ (cx, cy, 1)
            rect += (nx - cx, ny - cy, nx - cx, ny - cy)
        return rect * scale + (ox, oy, ox, oy)

    # 先在转正后的图片坐标中处理（文字都是横排），最后统一换算成页面坐标
    # 倾斜校正放大了画布：转正后的尺寸和坐标扣掉四周的边距，Word 的纸张大小与原页一致
    px, py = pad if angle in (0, 180) else pad[::-1]
    result = Result(angle=angle, skew=skew, upright_size=((w - 2 * px) * scale, (h - 2 * py) * scale))
    ocr = res.get("overall_ocr_res") or {}
    for text, score, box in zip(ocr.get("rec_texts", []), ocr.get("rec_scores", []), ocr.get("rec_boxes", [])):
        if text.strip():
            result.lines.append(Line(text=normalize_text(text), score=float(score), rect=pymupdf.Rect(box), angle=0))
    for block in res.get("parsing_res_list", []):
        rect = pymupdf.Rect(block["block_bbox"])
        inside = [line for line in result.lines if rect.contains(_center(line.rect))]
        result.blocks.append(
            Block(
                label=block["block_label"],
                content=normalize_text(str(block.get("block_content") or "")),
                rect=rect,
                font_size=_font_size(inside, scale),
            )
        )
    # 单元格坐标相对转正后的图片，补识别时从转正后的图片上裁剪
    tables = iter(res.get("table_res_list") or [])
    upright_img = (out["doc_preprocessor_res"] or {}).get("output_img") if angle else bgr
    for block in result.blocks:
        if block.label == "table" and (table_res := next(tables, None)) and upright_img is not None:
            block.content = repair_table(block.content, table_res, upright_img)
    _recover_orphan_lines(result, scale)

    for line in result.lines:
        line.rect, line.angle = to_page(line.rect), (360 - angle) % 360
    for block in result.blocks:
        block.upright = (block.rect - (px, py, px, py)) * scale
        block.rect = to_page(block.rect)
    return result


def estimate_skew(bgr: np.ndarray) -> float:
    """估算扫描图的倾斜角度：返回把图片转正需要旋转的角度（度，逆时针为正），不需要校正时返回 0。

    投影法：文字行、表格线转到水平时，逐行累加的墨迹量起伏最大。图片缩小到长边 1000 像素，
    在 ±OCR_DESKEW_MAX 度内先按 0.25° 粗找，再在附近按 0.025° 细找，每页约 0.1 秒。
    """
    import cv2

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    k = 1000 / max(gray.shape)
    if k < 1:
        gray = cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if ink.mean() < 0.002:  # 几乎空白
        return 0.0
    h, w = ink.shape

    def sharpness(a: float) -> float:
        m = cv2.getRotationMatrix2D((w / 2, h / 2), float(a), 1.0)
        rows = cv2.warpAffine(ink, m, (w, h), flags=cv2.INTER_NEAREST).sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(rows) ** 2))

    limit = config.OCR_DESKEW_MAX
    best = max(np.arange(-limit, limit + 1e-6, 0.25), key=sharpness)
    best = max(np.arange(best - 0.25, best + 0.25 + 1e-6, 0.025), key=sharpness)
    # 在搜索范围边上说明真实角度超出范围（或者是竖排、图片），不校正
    return 0.0 if abs(best) < 0.1 or abs(best) > limit - 0.25 else round(float(best), 3)


def deskew(bgr: np.ndarray) -> tuple[np.ndarray, float, np.ndarray | None, tuple[float, float]]:
    """倾斜校正。返回（转正后的图片，角度，从转正后图片坐标换算回原图坐标的 2×3 仿射矩阵，画布左右、上下各放大的像素）。

    画布按旋转后的外接矩形放大，四角不会被裁掉。小图（如混合页里的小图片）不处理：估算不可靠。
    """
    if not config.OCR_DESKEW or min(bgr.shape[:2]) < 300:
        return bgr, 0.0, None, (0.0, 0.0)
    angle = estimate_skew(bgr)
    if not angle:
        return bgr, 0.0, None, (0.0, 0.0)
    import cv2

    h, w = bgr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos + 0.5), int(h * cos + w * sin + 0.5)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    out = cv2.warpAffine(bgr, m, (nw, nh), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    return out, angle, cv2.invertAffineTransform(m), ((nw - w) / 2, (nh - h) / 2)


def _font_size(lines: list["Line"], scale: float) -> float:
    """按「行宽 ÷ 字数」估算字号（磅）：中文和全角字符宽 1 个字号，半角字符约 0.55 个。

    识别框的高度含外扩边距，与字号关系不稳定；字符宽度更准确。取中位数，按半磅取整。
    """
    sizes = []
    for line in lines:
        units = sum(1.0 if ord(ch) >= 0x2E80 else 0.55 for ch in line.text if not ch.isspace())
        if units >= 2:
            sizes.append(line.rect.width * scale / units)
    if not sizes:
        return 0
    return round(min(max(float(np.median(sizes)), 6), 36) * 2) / 2


class _CellParser(HTMLParser):
    """按顺序取出 HTML 表格的单元格（含 rowspan / colspan 属性）。"""

    def __init__(self):
        super().__init__()
        self.rows: list[list[dict]] = []
        self._cell: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            self._cell = {"attrs": {k: v for k, v in attrs if k in ("rowspan", "colspan")}, "text": ""}

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self.rows[-1].append(self._cell)
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def _cells_from_ocr(boxes: list[pymupdf.Rect], lines: list[tuple[str, pymupdf.Rect]]) -> tuple[list[str], set[int]]:
    """按坐标把识别出的行分配到单元格；一行跨多个单元格时（相邻格子的文字被识别成一行），按位置比例拆开。

    返回（每格文字，分到了拆分文字的单行格子）。按比例拆开常常切偏一两个字符（「DC-3000」→「DC-300」、
    「5 2026-10-25」），这些格子由调用方裁剪后单独识别。多行文字的格子单独识别会丢字，不在其中：
    格子只分到一段文字，或者高度不到识别行高的 1.6 倍，才算单行。
    """
    texts = [""] * len(boxes)
    sources = [0] * len(boxes)  # 每格分到了几段文字
    split: set[int] = set()
    for text, rect in sorted(lines, key=lambda x: (x[1].y0, x[1].x0)):
        hits = []
        for i, box in enumerate(boxes):
            overlap = rect & box
            if not overlap.is_empty and overlap.height > rect.height * 0.5:
                hits.append((overlap.width, i, box))
        hits = [h for h in hits if h[0] > rect.width * 0.1]
        if not hits:
            continue
        if len(hits) == 1:
            i = hits[0][1]
            texts[i] = _join(texts[i], text) if texts[i] else text
            sources[i] += 1
            continue
        # 按单元格左右边界拆分文字（按字符等宽估算）
        hits.sort(key=lambda h: h[2].x0)
        start = 0
        for n, (_, i, box) in enumerate(hits):
            end = len(text) if n == len(hits) - 1 else round(len(text) * (min(box.x1, rect.x1) - rect.x0) / rect.width)
            piece = text[start:end].strip()
            if piece:
                texts[i] = _join(texts[i], piece) if texts[i] else piece
                sources[i] += 1
                split.add(i)
            start = end
    line_height = float(np.median([r.height for _, r in lines])) if lines else 0
    return texts, {i for i in split if sources[i] == 1 or boxes[i].height < line_height * 1.6}


_DASHES = {"-", "－", "–", "—", "―", "−", "一", "--", "——"}


def repair_table(html: str, table_res: dict, image: np.ndarray) -> str:
    """用单元格坐标重新填表：PP-StructureV3 会丢掉跨格的文字行，检测模型也会漏掉很小的单个字符。

    单元格数量与表格结构对不上时不修复，保留原结果。
    """
    boxes = [pymupdf.Rect(b) for b in table_res.get("cell_box_list") or []]
    parser = _CellParser()
    parser.feed(html)
    cells = [c for row in parser.rows for c in row]
    if not boxes or len(boxes) != len(cells):
        return html

    table_ocr = table_res.get("table_ocr_pred") or {}
    lines = [
        (normalize_text(t), pymupdf.Rect(b))
        for t, b in zip(table_ocr.get("rec_texts", []), table_ocr.get("rec_boxes", []))
        if t.strip()
    ]
    texts, split = _cells_from_ocr(boxes, lines)

    # 仍为空的单元格、文字是按比例拆出来的单元格：裁剪后单独识别一次
    redo = [i for i, t in enumerate(texts) if (not t or i in split) and boxes[i].width > 8 and boxes[i].height > 8]
    if redo:
        h, w = image.shape[:2]
        crops = []
        for i in redo:
            b = boxes[i]
            pad = 3  # 去掉表格线
            x0, y0 = int(max(b.x0 + pad, 0)), int(max(b.y0 + pad, 0))
            x1, y1 = int(min(b.x1 - pad, w)), int(min(b.y1 - pad, h))
            crops.append(np.ascontiguousarray(image[y0:y1, x0:x1]))
        for i, out in zip(redo, recognizer().predict(crops)):
            text, score = out.json["res"].get("rec_text", ""), out.json["res"].get("rec_score", 0)
            text = text.strip()
            if not texts[i] and text in _DASHES and score >= 0.3:
                # 空格子里单独一笔横线是「无」的占位符，识别得分通常只有 0.4–0.5，也容易认成「一」
                texts[i] = "—"
            # 拆分出的文字已有内容，单独识别要更有把握才替换
            elif text and score >= (0.8 if texts[i] else 0.6):
                texts[i] = normalize_text(text)

    for cell, text in zip(cells, texts):
        text = text or cell["text"].strip()
        cell["text"] = "—" if text in _DASHES else text  # 整格只有一笔横线：统一为「—」
    rows = []
    for row in parser.rows:
        tds = "".join(
            "<td{}>{}</td>".format("".join(f' {k}="{v}"' for k, v in c["attrs"].items()), escape(c["text"]))
            for c in row
        )
        rows.append(f"<tr>{tds}</tr>")
    return "<table>" + "".join(rows) + "</table>"


def _center(rect: pymupdf.Rect) -> pymupdf.Point:
    return (rect.tl + rect.br) / 2


def _join(a: str, b: str) -> str:
    # 中文按排版换行直接拼接；两侧都是英文或数字时补一个空格
    return a + (" " if a[-1:].isascii() and a[-1:].isalnum() and b[:1].isascii() and b[:1].isalnum() else "") + b


# 列表项、条款的开头，从这里开始新段落
_ITEM_START = re.compile(r"^\s*([0-9]+[.、．)）]|[（(][0-9一二三四五六七八九十]+[)）]|[一二三四五六七八九十]+、|第[一二三四五六七八九十百0-9]+[条章节款]|[•·●■▪-])")
# 数字中的全角逗号（千分位）是 OCR 常见错误：353，370.00 → 353,370.00
_DIGIT_COMMA = re.compile(r"(?<=\d)，(?=\d{3}(?!\d))")


def normalize_text(text: str) -> str:
    return _DIGIT_COMMA.sub(",", text)


# 版面模型有时把多个列表项放进同一个文字块：在中文句末之后出现的序号处拆开（不认英文句点，避免拆开 1.2.3 这类编号）
_ITEM_BREAK = re.compile(r"(?<=[。；！？])\s*(?=(?:[0-9]+[.、．)）]|[（(][0-9一二三四五六七八九十]+[)）])\S)")


def split_items(text: str) -> list[str]:
    return [t.strip() for t in _ITEM_BREAK.split(text) if t.strip()]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _is_covered(line: Line, blocks: list[Block]) -> bool:
    """行与某个版面块重叠超过一半，或者文字已经包含在块的内容里。"""
    area = line.rect.get_area() or 1
    text = _compact(line.text)
    for block in blocks:
        if (line.rect & block.rect).get_area() / area > 0.5:
            return True
        if text and text in _compact(block.content):
            return True
    return False


# 「甲方：」「日期：」这类短标签开头的行
_LABEL_START = re.compile(r"^\s*[\u4e00-\u9fff]{1,6}[：:]")


def _starts_paragraph(line: Line, paragraph: list[Line]) -> bool:
    """列表项、短标签开头的行，或上一行以句末标点结尾且没有写满（段落在那里结束），都开始新段落。"""
    if _ITEM_START.match(line.text) or _LABEL_START.match(line.text):
        return True
    prev = paragraph[-1]
    full_width = max(l.rect.width for l in paragraph)
    return prev.text.rstrip()[-1:] in "。；！？：" and prev.rect.width < full_width * 0.85


def _recover_orphan_lines(result: Result, scale: float) -> None:
    """版面模型漏检的区域：识别出的行不在任何版面块内，PP-StructureV3 会直接丢掉这些文字。

    把这些行按上下间距合并成段落，作为 text 块按位置插回阅读顺序，保证不丢字。
    """
    orphans = [l for l in result.lines if not _is_covered(l, result.blocks)]
    # 先把同一行的片段归在一起（扫描件倾斜时同一行片段的 y 坐标略有差异），行内从左到右
    rows: list[Line] = []
    for line in sorted(orphans, key=lambda l: (l.rect.y0 + l.rect.y1) / 2):
        if rows:
            last = rows[-1].rect
            overlap = min(line.rect.y1, last.y1) - max(line.rect.y0, last.y0)
            if overlap > min(line.rect.height, last.height) * 0.5:
                left, right = sorted((rows[-1], line), key=lambda l: l.rect.x0)
                rows[-1] = Line(text=f"{left.text}　{right.text}", score=min(left.score, right.score), rect=left.rect | right.rect, angle=0)
                continue
        rows.append(line)

    paragraphs: list[list[Line]] = []
    for line in rows:
        if paragraphs and not _starts_paragraph(line, paragraphs[-1]):
            last = paragraphs[-1][-1].rect
            gap = line.rect.y0 - last.y1
            overlap = min(line.rect.x1, last.x1) - max(line.rect.x0, last.x0)
            if gap < last.height * 0.6 and overlap > 0:
                paragraphs[-1].append(line)
                continue
        paragraphs.append([line])

    for lines in paragraphs:
        text = lines[0].text
        for line in lines[1:]:
            text = _join(text, line.text)
        rect = pymupdf.Rect(lines[0].rect)
        for line in lines[1:]:
            rect |= line.rect
        block = Block(label="text", content=text, rect=rect, font_size=_font_size(lines, scale))
        # 插到同一栏中第一个位于它下方的块之前
        index = next(
            (
                i
                for i, b in enumerate(result.blocks)
                if b.rect.y0 >= rect.y0 and min(b.rect.x1, rect.x1) - max(b.rect.x0, rect.x0) > 0
            ),
            len(result.blocks),
        )
        result.blocks.insert(index, block)
