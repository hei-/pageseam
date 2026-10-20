"""跨页表格合并的单元测试（不需要 OCR 模型）。

用法（在服务镜像中执行）: python -m pytest tests/test_tables.py，或 python tests/test_tables.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pymupdf  # noqa: E402

from docparser.markdown import merge_cross_page_tables, text_pages_markdown  # noqa: E402

MD_HEAD = "|序号|名称|金额|\n|---|---|---|"


def md_rows(a, b):
    return "\n".join(f"|{i}|设备{i}|{i * 100}.00|" for i in range(a, b))


def html_table(a, b, header=True):
    head = "<tr><td>序号</td><td>名称</td><td>金额</td></tr>" if header else ""
    rows = "".join(f"<tr><td>{i}</td><td>设备{i}</td><td>{i * 100}.00</td></tr>" for i in range(a, b))
    return f"<table>{head}{rows}</table>"


def test_markdown_repeated_header():
    pages = {1: "## 清单\n\n" + MD_HEAD + "\n" + md_rows(1, 20) + "\n\n- 3 -",
             2: MD_HEAD + "\n" + md_rows(20, 30) + "\n\n说明文字"}
    out, merged = merge_cross_page_tables(pages)
    assert merged == [{"pages": "1-2", "rows": 30}], merged
    assert out[1].count("|序号|名称|金额|") == 1 and "|29|设备29|" in out[1]
    assert out[2].strip() == "说明文字"


def test_html_three_pages_without_header():
    pages = {3: "正文\n\n" + html_table(1, 10), 4: html_table(10, 20, header=False), 5: html_table(20, 25, header=False) + "\n\n结尾"}
    out, merged = merge_cross_page_tables(pages)
    assert merged == [{"pages": "3-5", "rows": 25}], merged
    assert out[4] == "" and out[5].strip() == "结尾"
    assert out[3].count("<table>") == 1 and "<td>24</td>" in out[3]


def test_markdown_then_scanned_html():
    pages = {1: MD_HEAD + "\n" + md_rows(1, 5), 2: html_table(5, 8, header=True)}
    out, merged = merge_cross_page_tables(pages)
    assert merged == [{"pages": "1-2", "rows": 8}], merged
    assert out[1].count("<th>序号</th>") == 1 and "<td>7</td>" in out[1] and "|" not in out[1].split("\n", 1)[1]


def test_different_tables_not_merged():
    other = "|项目|说明|\n|---|---|\n|a|b|"
    out, merged = merge_cross_page_tables({1: MD_HEAD + "\n" + md_rows(1, 3), 2: other})
    assert merged == [] and out[2] == other


def test_text_between_not_merged():
    out, merged = merge_cross_page_tables({1: MD_HEAD + "\n" + md_rows(1, 3) + "\n\n表格后的说明", 2: MD_HEAD + "\n" + md_rows(3, 5)})
    assert merged == []


def test_blank_page_breaks_continuity():
    out, merged = merge_cross_page_tables({1: html_table(1, 3), 2: "", 3: html_table(3, 5, header=False)})
    assert merged == []


def test_markdown_split_row():
    pages = {1: "|序号|条款|说明|\n|---|---|---|\n|1|付款|合同签订后 7 日内支付|\n|2|质保|质保期 24 个月，期内",
             2: "|序号|条款|说明|\n|---|---|---|\n||保修|免费维修|\n|3|验收|10 日内组织"}
    out, merged = merge_cross_page_tables(pages)
    assert merged == [{"pages": "1-2", "rows": 4}], merged
    assert "|2|质保保修|质保期 24 个月，期内免费维修|" in out[1], out[1]


def test_html_split_row():
    first = "<table><tr><td>序号</td><td>条款</td></tr><tr><td>1</td><td>乙方应在接到通知后</td></tr></table>"
    second = "<table><tr><td></td><td>24 小时内响应。</td></tr><tr><td>2</td><td>其他</td></tr></table>"
    out, merged = merge_cross_page_tables({1: first, 2: second})
    assert merged == [{"pages": "1-2", "rows": 3}], merged
    assert "<td>乙方应在接到通知后 24 小时内响应。</td>" in out[1] or "<td>乙方应在接到通知后24 小时内响应。</td>" in out[1], out[1]


def test_wrapped_cell_row_in_page():
    from docparser.markdown import _merge_wrapped_rows

    text = "|序号|名称|数量|单价|\n|---|---|---|---|\n|60|接近开关|10|45.00|\n||M12|||\n|61|继电器|20|28.00|\n||空白序号|5|1.00|"
    out = _merge_wrapped_rows(text).splitlines()
    assert out[2] == "|60|接近开关 M12|10|45.00|", out
    assert out[3].startswith("|61|") and out[4] == "||空白序号|5|1.00|", out  # 一半以上有内容的行不合并



def test_page_numbers_stripped():
    """每页开头、结尾的页码行去掉；续页只剩页码时整页为空，不会变成只有页码的分段。正文中间的数字保留。"""
    pages = {1: "清单\n\n" + MD_HEAD + "\n" + md_rows(1, 20) + "\n\n- 1 -",
             2: MD_HEAD + "\n" + md_rows(20, 30) + "\n\n- 2 -",
             3: "第 3 页 共 3 页\n\n说明\n\n2026\n\n结尾\n\n3/3"}
    out, merged = merge_cross_page_tables(pages)
    assert merged == [{"pages": "1-2", "rows": 30}], merged
    assert "- 1 -" not in out[1] and out[2] == "", out
    assert out[3] == "说明\n\n2026\n\n结尾", out[3]


CJK_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def _spanned_table_pdf() -> pymupdf.Document:
    """两行表头（「输出功率」下分「额定」「峰值」）、三列纵向合并两行的表格，合并单元格的文字垂直居中。"""
    doc = pymupdf.open()
    page = doc.new_page()
    # 镜像里的 Noto Sans CJK（fonts-noto-cjk）：内置的 china-s 字体西文按全角排、没有「℃」，排出来会溢出单元格
    page.insert_font(fontname="noto", fontfile=CJK_FONT)
    xs = [50, 130, 210, 270, 340, 410, 490]
    ys = [100, 124, 148, 172, 196, 220, 244]
    # （第几行, 第几列, 跨几行, 跨几列, 文字）
    cells = [(0, 0, 2, 1, "系列"), (0, 1, 2, 1, "型号"), (0, 2, 2, 1, "电池容量"), (0, 3, 1, 2, "输出功率"),
             (1, 3, 1, 1, "额定"), (1, 4, 1, 1, "峰值"), (0, 5, 2, 1, "工作温度"),
             (2, 0, 1, 1, "SP-100 系列"), (2, 1, 1, 1, "SP-100"), (2, 2, 1, 1, "268 Wh"), (2, 3, 1, 1, "330 W"),
             (2, 4, 1, 1, "610 W"), (2, 5, 1, 1, "-10 ~ 40 ℃"),
             (3, 0, 2, 1, "SP-200 系列"), (3, 1, 1, 1, "SP-200"), (3, 2, 2, 1, "512 Wh"), (3, 3, 1, 1, "413 W"),
             (3, 4, 1, 1, "930 W"), (3, 5, 2, 1, "-15 ~ 45 ℃"),
             (4, 1, 1, 1, "SP-200 Pro"), (4, 3, 1, 1, "487 W"), (4, 4, 1, 1, "1,180 W"),
             (5, 0, 1, 1, "SP-300 系列"), (5, 1, 1, 1, "SP-300"), (5, 2, 1, 1, "1,036 Wh"), (5, 3, 1, 1, "1,150 W"),
             (5, 4, 1, 1, "2,060 W"), (5, 5, 1, 1, "-20 ~ 45 ℃")]
    for r, c, rs, cs, text in cells:
        rect = pymupdf.Rect(xs[c], ys[r], xs[c + cs], ys[r + rs])
        page.draw_rect(rect, color=(0, 0, 0), width=0.6)
        page.insert_text((rect.x0 + 4, (rect.y0 + rect.y1) / 2 + 3.5), text, fontname="noto", fontsize=9)
    page.insert_text((50, 80), "型号对比", fontname="noto", fontsize=14)
    return doc


def test_spanned_cells_expanded():
    """纵向合并的值填到它覆盖的每一行，两行表头拼成「输出功率/额定」，合并单元格里的连字符不丢。"""
    md = text_pages_markdown(_spanned_table_pdf(), [1])[1]
    md = md.replace("\u2011", "-").replace("\xa0", " ")  # insert_text 写入的连字符、空格提取出来是 U+2011、U+00A0
    rows = [line for line in md.splitlines() if line.startswith("|")]
    assert rows[0] == "|系列|型号|电池容量|输出功率/额定|输出功率/峰值|工作温度|", md
    assert "|SP-200 系列|SP-200|512 Wh|413 W|930 W|-15 ~ 45 ℃|" in rows, md
    assert "|SP-200 系列|SP-200 Pro|512 Wh|487 W|1,180 W|-15 ~ 45 ℃|" in rows, md
    assert "|SP-300 系列|SP-300|1,036 Wh|1,150 W|2,060 W|-20 ~ 45 ℃|" in rows, md
    assert len(rows) == 6, md  # 表头、分隔行、4 行数据


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
