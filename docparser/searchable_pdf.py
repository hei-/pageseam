"""生成可搜索 PDF：原页面完全不动，在 OCR 识别出文字的位置叠加一层看不见的文字。

外观和原件一致，文字可以选中、复制、搜索。扫描件原有的旧 OCR 层会先删除，避免搜索到两份不一致的文字。
"""

import pymupdf

from docparser.classify import SCAN_OLD_OCR, PageInfo
from docparser.ocr import Result

_font: pymupdf.Font | None = None


def font() -> pymupdf.Font:
    """PyMuPDF 内置的 CJK 字体（Droid Sans Fallback），保存时按用到的字子集化。"""
    global _font
    if _font is None:
        _font = pymupdf.Font("cjk")
    return _font


def remove_text_layer(page: pymupdf.Page) -> None:
    """删除页面上的全部文字，保留图片和矢量图形。只用于扫描页的旧 OCR 层。"""
    page.add_redact_annot(page.rect)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )


def add_text_layer(page: pymupdf.Page, result: Result) -> int:
    """逐行写入隐藏文字，按识别框拉伸宽度，选中文字时高亮范围和原图对齐。返回写入的行数。

    识别坐标是页面显示坐标；写入使用未旋转坐标，带 /Rotate 的页面要换算，文字方向也要加上页面旋转角度。
    """
    f = font()
    count = 0
    for line in result.lines:
        rect = line.rect
        vertical = line.angle in (90, 270)
        length, size = (rect.height, rect.width) if vertical else (rect.width, rect.height)
        fontsize = size * 0.8
        natural = f.text_length(line.text, fontsize=fontsize)
        if natural <= 0 or fontsize < 1:
            continue
        # 基线起点（显示坐标）。angle 是文字方向相对页面的逆时针角度
        descent = size * 0.2
        if line.angle == 0:  # 从左到右
            anchor = pymupdf.Point(rect.x0, rect.y1 - descent)
        elif line.angle == 90:  # 从下到上
            anchor = pymupdf.Point(rect.x1 - descent, rect.y1)
        elif line.angle == 180:  # 倒置，从右到左
            anchor = pymupdf.Point(rect.x1, rect.y0 + descent)
        else:  # 270：从上到下
            anchor = pymupdf.Point(rect.x0 + descent, rect.y0)
        anchor = anchor * page.derotation_matrix

        writer = pymupdf.TextWriter(page.rect)
        writer.append(anchor, line.text, font=f, fontsize=fontsize)
        # 以基线起点为中心：先沿文字方向拉伸到识别框长度，再旋转（Matrix(角度) 为逆时针）
        matrix = pymupdf.Matrix(length / natural, 1) * pymupdf.Matrix(line.angle + page.rotation)
        writer.write_text(page, render_mode=3, morph=(anchor, matrix))
        count += 1
    return count


def build(src: pymupdf.Document, pages: list[PageInfo], results: dict[int, list[Result]], out_path: str) -> None:
    """pages 为本次处理的页（按顺序）；results 为 {页码: [整页或各区域的识别结果]}。"""
    doc = pymupdf.open()
    doc.insert_pdf(src)
    keep = [info.page - 1 for info in pages]
    if len(keep) != doc.page_count:
        doc.select(keep)
    for index, info in enumerate(pages):
        page = doc[index]
        if info.kind == SCAN_OLD_OCR:
            remove_text_layer(page)
        for result in results.get(info.page, []):
            add_text_layer(page, result)
    doc.subset_fonts()
    doc.save(out_path, garbage=3, deflate=True)
