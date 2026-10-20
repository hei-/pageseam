"""文字型页清理的单元测试：页眉页脚、部首码位、docx 默认东亚语言（不需要 OCR 模型）。

用法（在服务镜像中执行）: python -m pytest tests/test_text.py，或 python tests/test_text.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from docparser.convert import fix_east_asian_language  # noqa: E402
from docparser.markdown import merge_cross_page_tables, normalize_radicals, strip_running_lines  # noqa: E402

HEADER = "云杉智能 SP 系列用户手册 · 内部测试文档"
MD_HEAD = "|错误码|含义|\n|---|---|"


def test_running_header_and_footer_removed():
    """每页都有的页眉、带页码的页脚去掉；只在第 1 页出现的标题、正文保留。"""
    words = {1: ("保修期限", "保修范围"), 2: ("退货条件", "换货条件"), 3: ("寄修流程", "上门服务")}
    pages = {n: f"{HEADER}\n\n{a}说明。\n\n{b}说明。\n\n内部资料 第 {n} 页" for n, (a, b) in words.items()}
    pages[1] = f"{HEADER}\n\n# 保修政策\n\n" + pages[1].split("\n\n", 1)[1]
    out, removed = strip_running_lines(pages)
    assert removed == [HEADER, "内部资料 第 1 页"], removed
    assert out[1] == "# 保修政策\n\n保修期限说明。\n\n保修范围说明。", out[1]
    assert out[3] == "寄修流程说明。\n\n上门服务说明。", out[3]


def test_header_between_tables_does_not_block_merge():
    """页眉夹在两页表格之间时，先去掉页眉，跨页表格才能合并。"""
    pages = {1: f"{HEADER}\n\n# 错误码速查表\n\n{MD_HEAD}\n|E-1003|电压不均衡|",
             2: f"{HEADER}\n\n|E-1042|通信中断|\n|---|---|\n|E-1055|容量衰减|\n\n说明文字"}
    out, removed = strip_running_lines(pages)
    out, merged = merge_cross_page_tables(out)
    assert removed == [HEADER] and merged == [{"pages": "1-2", "rows": 4}], (removed, merged)
    assert "|E-1042|通信中断|" in out[1] and out[2] == "说明文字", out


def test_kept_when_not_running():
    """单页文档、只出现在一页的行、标题、纯数字、表格、页面中间重复的句子都不去掉。"""
    single = {1: f"{HEADER}\n\n正文"}
    assert strip_running_lines(single) == (single, [])
    middle = "注意：请勿拆机。"
    words = {1: ("安装", "接线"), 2: ("调试", "验收"), 3: ("保养", "维修")}
    pages = {n: f"# {a}\n\n{a}说明\n\n{middle}\n\n{b}说明\n\n小计 {n * 300}\n\n2026" for n, (a, b) in words.items()}
    out, removed = strip_running_lines(pages)
    assert out == pages and removed == [], removed
    tables = {n: f"{MD_HEAD}\n|E-{n}|含义{n}|" for n in (1, 2)}
    assert strip_running_lines(tables) == (tables, [])


def test_half_of_pages():
    """在一半以上有内容的页面出现才算页眉：4 页里出现 2 页算，空白页不计。"""
    pages = {1: f"{HEADER}\n\n安装", 2: f"{HEADER}\n\n调试", 3: "保养", 4: "维修", 5: ""}
    out, removed = strip_running_lines(pages)
    assert removed == [HEADER] and out[1] == "安装" and out[5] == "", out
    pages[2] = "调试"
    out, removed = strip_running_lines(pages)
    assert removed == [] and out == pages


def test_radicals_normalized():
    """康熙部首和部首补充里独立成字的换回常用字，偏旁形式和普通文字不变。"""
    text = "⻋载使⽤时，⻓时间停⻋请勿留在前挡⻛玻璃下⽅，帮助⻚⾯搜索“⻋型”。"
    assert normalize_radicals(text) == "车载使用时，长时间停车请勿留在前挡风玻璃下方，帮助页面搜索“车型”。"
    assert normalize_radicals("⺅⻊ SP-200（全角）") == "⺅⻊ SP-200（全角）"
    # 兼容表意文字（字体把常用字映射到 U+F900–FAFF）换回统一码位；本身就是统一表意文字的（﨎）不变
    assert normalize_radicals("\uf99c\uf97e 输出功\uf9db 工作温\ufa01 \ufa0e") == "列量 输出功率 工作温度 \ufa0e"



def _docx(body: str, lang: str) -> dict[str, bytes]:
    styles = ('<w:styles><w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="22"/>'
              f'{lang}</w:rPr></w:rPrDefault></w:docDefaults><w:style w:styleId="a"><w:rPr><w:lang w:val="fr-FR"/></w:rPr></w:style></w:styles>')
    return {"word/document.xml": f"<w:body><w:t>{body}</w:t></w:body>".encode(), "word/styles.xml": styles.encode()}


def test_east_asian_language():
    """正文是中文、默认东亚语言是 en-US 或没写时改成 zh-CN（引号才会用中文字体渲染）；
    已经是中日韩语言、正文没有中日韩文字时不改；只改默认设置，不动其他样式。"""
    zh = "搜索关键词“车型”。"
    data = _docx(zh, '<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-SA"/>')
    assert fix_east_asian_language(data)
    styles = data["word/styles.xml"].decode()
    assert '<w:lang w:val="en-US" w:eastAsia="zh-CN" w:bidi="ar-SA"/>' in styles and 'w:val="fr-FR"' in styles, styles
    data = _docx(zh, '<w:lang w:val="en-US"/>')
    assert fix_east_asian_language(data) and 'w:eastAsia="zh-CN"' in data["word/styles.xml"].decode()
    data = _docx(zh, "")
    assert fix_east_asian_language(data) and '<w:lang w:eastAsia="zh-CN"/>' in data["word/styles.xml"].decode()
    data = _docx("「型式」を検索", '<w:lang w:eastAsia="en-US"/>')
    assert fix_east_asian_language(data) and 'w:eastAsia="ja-JP"' in data["word/styles.xml"].decode()
    assert not fix_east_asian_language(_docx(zh, '<w:lang w:eastAsia="zh-TW"/>'))
    assert not fix_east_asian_language(_docx("Search “model”.", '<w:lang w:eastAsia="en-US"/>'))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
