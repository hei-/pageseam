"""扫描表格评测：逐格比对识别结果和标准答案，算出单元格准确率。

只检查关键字段是否出现，发现不了「值都识别出来了，但落在错误的列」（倾斜 0.6° 就会出现）。
这里把已知内容的表格渲染成不同倾斜角度的扫描图，分别作为 PDF 扫描页和 JPEG 图片识别，
展开合并单元格后按（行，列）逐格比对。

用法（在服务镜像中执行）: python tests/eval_tables.py [--angles 0,0.5,-1] [--tables 交付计划,物料清单] [--paths jpeg] [--quick] [--min 0.95]
--quick 只测 PDF 路径、角度 0/±1/3；--min 设置后任一用例低于该准确率时退出码为 1。
"""

import argparse
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import pymupdf  # noqa: E402
from make_sample import ATTACHMENT_HTML, CONTRACT_HTML, DELIVERY_HTML, render_scan  # noqa: E402
from make_tables_sample import ACCEPT_HEAD, ACCEPTANCE, MATERIAL_HEAD, MATERIALS, accept_rows, material_rows  # noqa: E402

from docparser import ocr  # noqa: E402
from docparser.convert import image_to_pdf  # noqa: E402

LANDSCAPE = pymupdf.paper_rect("a4-l")
A4 = pymupdf.paper_rect("a4")

# （名称，HTML，页面大小）。合同第一条带 colspan 的合计行，验收记录 21 行，物料清单数字多
TABLES = [
    ("交付计划", DELIVERY_HTML, LANDSCAPE),
    ("采购设备", CONTRACT_HTML, A4),
    ("技术参数", ATTACHMENT_HTML, A4),
    ("验收记录", f"<h2>设备验收记录</h2><table>{ACCEPT_HEAD}{accept_rows(ACCEPTANCE)}</table>", A4),
    ("物料清单", f"<h2>备品备件清单</h2><table>{MATERIAL_HEAD}{material_rows(MATERIALS[:20], 1)}</table>", LANDSCAPE),
]
ANGLES = [0, 0.3, -0.3, 0.6, -0.6, 1, -1, 2, -2, 3]
QUICK_ANGLES = [0, 1, -1, 3]


def grid(html: str) -> list[list[str]]:
    """HTML 表格展开成二维网格：合并单元格的内容放在左上角，其余位置为空。"""
    parser = ocr._CellParser()
    parser.feed(html)
    out: list[list[str]] = []
    taken: set[tuple[int, int]] = set()
    for r, row in enumerate(parser.rows):
        while len(out) <= r:
            out.append([])
        c = 0
        for cell in row:
            while (r, c) in taken:
                c += 1
            rs, cs = int(cell["attrs"].get("rowspan", 1)), int(cell["attrs"].get("colspan", 1))
            for dr in range(rs):
                for dc in range(cs):
                    taken.add((r + dr, c + dc))
                    while len(out) <= r + dr:
                        out.append([])
                    line = out[r + dr]
                    line.extend([""] * (c + dc + 1 - len(line)))
                    line[c + dc] = cell["text"] if dr == dc == 0 else ""
            c += cs
    width = max((len(r) for r in out), default=0)
    return [r + [""] * (width - len(r)) for r in out]


def norm(text: str) -> str:
    """比较时忽略空白和全角半角差异（OCR 常把「（」识别成「(」）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def score(truth: list[list[str]], got: list[list[str]]) -> tuple[int, int]:
    """（正确的格数，标准答案的格数）。按位置比对，形状不同时多出、缺少的格都算错。"""
    total = sum(len(r) for r in truth)
    right = sum(
        1
        for r, row in enumerate(truth)
        for c, text in enumerate(row)
        if r < len(got) and c < len(got[r]) and norm(got[r][c]) == norm(text)
    )
    return right, total


def table_html(source: str) -> str:
    return re.search(r"<table>.*?</table>", source, re.S).group(0)


def scanned(html: str, rect: pymupdf.Rect, angle: float, path: str) -> pymupdf.Document:
    jpeg = render_scan(html, rect=rect, angle=angle, seal=False)
    if path == "jpeg":  # 与上传图片时相同
        return pymupdf.open("pdf", image_to_pdf(jpeg))
    doc = pymupdf.open()
    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(page.rect, stream=jpeg)
    return doc


def first_diff(truth, got) -> str:
    for r, row in enumerate(truth):
        for c, text in enumerate(row):
            value = got[r][c] if r < len(got) and c < len(got[r]) else "∅"
            if norm(value) != norm(text):
                return f"第 {r + 1} 行第 {c + 1} 列：应为「{text}」，识别为「{value}」"
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--angles", help="逗号分隔的倾斜角度")
    ap.add_argument("--tables", help="逗号分隔的表格名称")
    ap.add_argument("--paths", help="pdf、jpeg，逗号分隔")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--min", type=float, default=0)
    args = ap.parse_args()
    angles = [float(a) for a in args.angles.split(",")] if args.angles else (QUICK_ANGLES if args.quick else ANGLES)
    paths = args.paths.split(",") if args.paths else (["pdf"] if args.quick else ["pdf", "jpeg"])
    tables = [t for t in TABLES if not args.tables or t[0] in args.tables.split(",")]

    results = []  # （表格，路径，角度，正确，总数，耗时，第一个错误）
    for name, source, rect in tables:
        truth = grid(table_html(source))
        for path in paths:
            for angle in angles:
                with scanned(source, rect, angle, path) as doc:
                    start = time.time()
                    res = ocr.recognize(doc[0])
                    took = time.time() - start
                found = [b.content for b in res.blocks if b.label == "table"]
                got = grid(found[0]) if found else []
                right, total = score(truth, got)
                results.append((name, path, angle, right, total, took, first_diff(truth, got)))
                r = results[-1]
                print(f"{'✅' if right == total else '❌'} {name} {path} {angle:+.1f}°  {right}/{total}  {took:.1f}s  "
                      f"校正 {res.skew:+.2f}°  {r[6]}", flush=True)

    print("\n按角度汇总（单元格准确率）:")
    for angle in angles:
        rows = [r for r in results if r[2] == angle]
        right, total = sum(r[3] for r in rows), sum(r[4] for r in rows)
        perfect = sum(r[3] == r[4] for r in rows)
        print(f"  {angle:+.1f}°  {right / total:.3f}  全对 {perfect}/{len(rows)}")
    right, total = sum(r[3] for r in results), sum(r[4] for r in results)
    perfect = sum(r[3] == r[4] for r in results)
    print(f"\n总计：单元格准确率 {right / total:.3f}，全对的表格 {perfect}/{len(results)}，"
          f"平均每页 {sum(r[5] for r in results) / len(results):.1f} 秒")
    worst = min(r[3] / r[4] for r in results)
    sys.exit(1 if args.min and worst < args.min else 0)


if __name__ == "__main__":
    main()
