"""端到端检查：用 make_sample.py 生成的混合 PDF 跑完整流程，逐项验证三种输出。

用法（在服务镜像中执行）: python tests/check_pipeline.py sample.pdf /tmp/out
"""

import json
import os
import shutil
import sys

import pymupdf
from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from docparser import pipeline  # noqa: E402

EXPECTED_KINDS = ["text", "text", "scan", "scan_old_ocr", "mixed", "garbled", "blank", "scan", "scan", "scan"]
# 每页应能搜索到的文字（可搜索 PDF 和 Word 中都要有）
EXPECTED_TEXT = {
    1: "1,177,900.00",
    2: "353,370.00",
    3: "协商不成",
    4: "备品备件",
    5: "800×500×550",
    6: "操作培训",
    8: "安装调试完成",
    9: "试运行",
    10: "补充协议",
}

# Word 中混合页的扫描表格图片替换成可编辑的表格（word_images=replace），所以第 5 页也要能找到表格内容
WORD_EXPECTED = {**EXPECTED_TEXT, 5: "800×500×550"}

failures = []


def check(ok: bool, message: str) -> None:
    print(("  ✅ " if ok else "  ❌ ") + message)
    if not ok:
        failures.append(message)


def main(sample: str, out_dir: str) -> None:
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    shutil.copy(sample, os.path.join(out_dir, "input.pdf"))
    src = pymupdf.open(sample)
    result = pipeline.run(
        out_dir,
        {"outputs": ["markdown", "pdf", "docx"], "ocr": "auto", "ocr_pages": [], "pages": list(range(1, src.page_count + 1))},
    )
    print(json.dumps({k: result[k] for k in ("summary", "timings")}, ensure_ascii=False))
    for p in result["pages"]:
        print(f"  p{p['page']:<2} {p['kind']:<13} {p['seconds'] or '':<5} angle={p.get('ocr_angle', '')} {p['reason']}")

    print("页面分类")
    kinds = [p["kind"] for p in result["pages"]]
    check(kinds == EXPECTED_KINDS, f"分类 {kinds}")

    print("可搜索 PDF")
    out = pymupdf.open(os.path.join(out_dir, "result.pdf"))
    check(out.page_count == src.page_count, f"页数 {out.page_count}")
    for i in range(src.page_count):
        same = src[i].get_pixmap(dpi=40).samples == out[i].get_pixmap(dpi=40).samples
        check(same, f"p{i + 1} 外观与原件一致")
    for page_no, text in EXPECTED_TEXT.items():
        page = out[page_no - 1]
        hits = page.search_for(text)  # 搜索结果是未旋转坐标
        inside = all(page.mediabox.contains(h) for h in hits)
        check(bool(hits) and inside, f"p{page_no} 能搜索到「{text}」{[tuple(round(v) for v in h) for h in hits]}")
    old_layer = out[3].get_text()
    check("热钱" not in old_layer, "p4 旧 OCR 层已删除")
    # 搜索结果高亮，供人工核对位置
    for page_no in (3, 9, 10):
        page = out[page_no - 1]
        for text in (EXPECTED_TEXT[page_no], "第"):
            for rect in page.search_for(text)[:6]:
                page.draw_rect(rect, color=(1, 0, 0), width=1.2)  # 绘图和搜索结果都是未旋转坐标
        page.get_pixmap(dpi=60).save(os.path.join(out_dir, f"highlight_p{page_no}.png"))

    print("Word")
    doc = Document(os.path.join(out_dir, "result.docx"))
    texts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            texts.extend(cell.text for cell in row.cells)
    full = "\n".join(texts)
    for page_no, text in WORD_EXPECTED.items():
        check(text in full, f"包含 p{page_no}「{text}」")
    orientations = [(round(s.page_width.pt), round(s.page_height.pt)) for s in doc.sections]
    check(len(doc.sections) >= 4, f"分节 {len(doc.sections)}：{orientations}")
    check(any(w > h for w, h in orientations), "保留横向页面")

    print("Markdown")
    with open(os.path.join(out_dir, "result.md"), encoding="utf-8") as f:
        md = f.read()
    check(all(f"<!-- page {n} -->" in md for n in range(1, 11)), "每页都有页码标记")
    for page_no, text in EXPECTED_TEXT.items():
        check(text in md, f"包含 p{page_no}「{text}」")
    check("<table>" in md, "OCR 表格保留为 HTML")

    print(f"\n{'全部通过' if not failures else f'{len(failures)} 项失败'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
