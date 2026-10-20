"""逐页判断要不要 OCR。

每页读取 4 项指标（文字量、有效字符比例、图片覆盖率、隐藏文字），按顺序匹配判定规则。
只用 PyMuPDF 读取 PDF 结构，不渲染页面，每页耗时毫秒级。
"""

from dataclasses import asdict, dataclass, field

import pymupdf

from docparser.i18n import t

# 判定阈值，可以通过环境变量覆盖（见 config.py）
DEFAULTS = {
    "min_text_chars": 20,  # 少于这个字数视为「几乎没有文字」
    "scan_image_coverage": 0.5,  # 图片覆盖超过这个比例，且几乎没有文字 → 扫描页
    "min_valid_ratio": 0.9,  # 有效字符比例低于这个值 → 乱码页
    "region_min_coverage": 0.1,  # 文字正常，但有单张图片超过页面这个比例 → 混合页，对这些图片做 OCR（跳过图标、Logo）
    "outline_min_drawings": 300,  # 没有文字但有大量矢量路径 → 文字被转成了曲线，需要 OCR
}

SCAN = "scan"  # 扫描页：整页 OCR
SCAN_OLD_OCR = "scan_old_ocr"  # 扫描页，带旧的隐藏文字层：删除旧层后整页 OCR
GARBLED = "garbled"  # 乱码页：整页 OCR
OUTLINED = "outlined"  # 文字转成了曲线：整页 OCR
MIXED = "mixed"  # 混合页：文字用原文，图片区域单独 OCR
TEXT = "text"  # 文字型页：不做 OCR
BLANK = "blank"  # 空白页：跳过
FORCED = "forced"  # 用户指定整页 OCR

FULL_OCR_KINDS = {SCAN, SCAN_OLD_OCR, GARBLED, OUTLINED, FORCED}



class PageRangeError(ValueError):
    """页码范围写错了，part 是出错的那一段。"""

    def __init__(self, part: str):
        super().__init__(t("bad_page_range", "en", part=part))
        self.part = part


def label(kind: str, lang: str | None = None) -> str:
    return t("kind." + kind, lang)


@dataclass
class PageInfo:
    page: int  # 从 1 开始
    kind: str
    label: str
    visible_chars: int
    hidden_chars: int
    valid_ratio: float
    image_coverage: float
    drawings: int
    width: float
    height: float
    rotation: int
    # 混合页中需要单独 OCR 的图片区域（页面显示坐标）
    ocr_regions: list[tuple[float, float, float, float]] = field(default_factory=list)
    reason: str = ""

    @property
    def full_ocr(self) -> bool:
        return self.kind in FULL_OCR_KINDS

    def to_dict(self) -> dict:
        data = asdict(self)
        data["image_coverage"] = round(self.image_coverage, 3)
        data["valid_ratio"] = round(self.valid_ratio, 3)
        data["ocr_regions"] = [[round(v, 1) for v in r] for r in self.ocr_regions]
        return data


def _is_valid_char(ch: str) -> bool:
    code = ord(ch)
    if code < 0x20:
        return False
    return (
        code < 0x7F  # ASCII
        or 0xA0 <= code <= 0x24F  # Latin-1、拉丁扩展（含 ± × ÷ ³ 等）
        or 0x370 <= code <= 0x4FF  # 希腊、西里尔（μ、Ω）
        or 0x2000 <= code <= 0x2BFF  # 通用标点、上下标、货币、字母式符号、数字形式、箭头、数学符号、制表符、几何图形、带圈数字
        or 0x2E80 <= code <= 0x9FFF  # CJK 部首、标点、假名、注音、CJK 扩展 A、CJK 统一汉字
        or 0xAC00 <= code <= 0xD7AF  # 韩文
        or 0xF900 <= code <= 0xFAFF  # CJK 兼容汉字
        or 0xFE30 <= code <= 0xFE4F  # CJK 兼容形式
        or 0xFF00 <= code <= 0xFFEF  # 全角字符
        or 0x20000 <= code <= 0x3134F  # CJK 扩展 B–G
    )


def _text_stats(page: pymupdf.Page) -> tuple[int, int, float]:
    """返回（可见字符数，隐藏字符数，有效字符比例），空白字符不计。"""
    visible = hidden = valid = 0
    for span in page.get_texttrace():
        # type 3 = 不可见文字（渲染模式 3），扫描件上的 OCR 层就是这种文字
        is_hidden = span.get("type") == 3 or span.get("opacity", 1) == 0
        for char in span["chars"]:
            ch = chr(char[0])
            if ch.isspace():
                continue
            if is_hidden:
                hidden += 1
                continue
            visible += 1
            if _is_valid_char(ch):
                valid += 1
    ratio = valid / visible if visible else 1.0
    return visible, hidden, ratio


def _fonts_without_unicode(page: pymupdf.Page) -> list[str]:
    """Identity-H 编码的 CID 字体如果没有 ToUnicode 映射，提取出来的是字形编号，即乱码。"""
    doc = page.parent
    names = []
    for xref, _ext, ftype, basefont, _name, encoding in page.get_fonts():
        if ftype == "Type0" and encoding.startswith("Identity") and doc.xref_get_key(xref, "ToUnicode")[0] in ("null", "undefined"):
            names.append(basefont)
    return names


def _image_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """图片位置，换算成页面显示坐标（与 page.rect、渲染和裁剪使用的坐标一致）。

    get_image_info 返回的是未旋转坐标，带 /Rotate 的页面需要换算。
    """
    rects = []
    for info in page.get_image_info():
        rect = (pymupdf.Rect(info["bbox"]) * page.rotation_matrix) & page.rect
        if not rect.is_empty:
            rects.append(rect)
    return rects


def _coverage(rects: list[pymupdf.Rect], area: pymupdf.Rect, grid: int = 100) -> float:
    """多个矩形的并集占页面的比例（栅格近似，图片相互重叠时不重复计算）。"""
    if not rects:
        return 0.0
    if len(rects) == 1:
        return min(rects[0].get_area() / area.get_area(), 1.0)
    cw, ch = area.width / grid, area.height / grid
    covered = set()
    for r in rects:
        x0, x1 = int((r.x0 - area.x0) / cw), int((r.x1 - area.x0) / cw + 0.999)
        y0, y1 = int((r.y0 - area.y0) / ch), int((r.y1 - area.y0) / ch + 0.999)
        for x in range(max(x0, 0), min(x1, grid)):
            for y in range(max(y0, 0), min(y1, grid)):
                covered.add((x, y))
    return len(covered) / (grid * grid)


def classify_page(page: pymupdf.Page, cfg: dict | None = None, lang: str | None = None) -> PageInfo:
    cfg = {**DEFAULTS, **(cfg or {})}
    visible, hidden, ratio = _text_stats(page)
    images = _image_rects(page)
    coverage = _coverage(images, page.rect)
    drawings = len(page.get_cdrawings()) if visible < cfg["min_text_chars"] else 0

    info = PageInfo(
        page=page.number + 1,
        kind=TEXT,
        label="",
        visible_chars=visible,
        hidden_chars=hidden,
        valid_ratio=ratio,
        image_coverage=coverage,
        drawings=drawings,
        width=page.rect.width,
        height=page.rect.height,
        rotation=page.rotation,
    )
    few_text = visible < cfg["min_text_chars"]

    if few_text and coverage >= cfg["scan_image_coverage"]:
        if hidden >= cfg["min_text_chars"]:
            info.kind, info.reason = SCAN_OLD_OCR, t("reason.scan_old_ocr", lang, hidden=hidden)
        else:
            info.kind, info.reason = SCAN, t("reason.scan", lang, visible=visible, coverage=coverage)
    elif few_text and drawings >= cfg["outline_min_drawings"]:
        info.kind, info.reason = OUTLINED, t("reason.outlined", lang, drawings=drawings)
    elif few_text and coverage == 0 and visible == 0:
        info.kind, info.reason = BLANK, t("reason.blank", lang)
    elif not few_text and ratio < cfg["min_valid_ratio"]:
        info.kind, info.reason = GARBLED, t("reason.garbled", lang, ratio=ratio)
    elif not few_text and (fonts := _fonts_without_unicode(page)):
        info.kind, info.reason = GARBLED, t("reason.no_unicode", lang, font=fonts[0])
    elif regions := [r for r in images if r.get_area() / page.rect.get_area() >= cfg["region_min_coverage"]]:
        info.kind = MIXED
        info.ocr_regions = [tuple(r) for r in regions]
        info.reason = t("reason.mixed", lang, visible=visible, regions=len(regions), coverage=coverage)
    else:
        info.reason = t("reason.text", lang, visible=visible, ratio=ratio)

    info.label = label(info.kind, lang)
    return info


def parse_page_ranges(spec: str | None, page_count: int) -> set[int]:
    """解析「1-3,5,8-」这样的页码范围，返回从 1 开始的页码集合。"""
    pages: set[int] = set()
    if not spec:
        return pages
    for part in spec.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start, _, end = part.partition("-")
                a = int(start) if start.strip() else 1
                b = int(end) if end.strip() else page_count
            else:
                a = b = int(part)
        except ValueError:
            raise PageRangeError(part) from None
        if a < 1 or b < a:
            raise PageRangeError(part)
        pages.update(range(a, min(b, page_count) + 1))
    return pages


def classify_document(
    doc: pymupdf.Document,
    ocr_mode: str = "auto",
    ocr_pages: set[int] | None = None,
    cfg: dict | None = None,
    lang: str | None = None,
) -> list[PageInfo]:
    """ocr_mode: auto 自动判断；force 所有非空白页整页 OCR；off 不做 OCR。"""
    result = []
    for page in doc:
        info = classify_page(page, cfg, lang)
        if info.kind != BLANK:
            if ocr_mode == "force" or (ocr_pages and info.page in ocr_pages):
                info.kind, info.label = FORCED, label(FORCED, lang)
                info.reason = t("reason.forced", lang) + info.reason
            elif ocr_mode == "off" and (info.full_ocr or info.kind == MIXED):
                info.reason = t("reason.off", lang, label=info.label) + info.reason
                info.kind, info.label, info.ocr_regions = TEXT, label(TEXT, lang), []
        result.append(info)
    return result
