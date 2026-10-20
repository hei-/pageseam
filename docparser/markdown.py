"""生成 Markdown（给知识库用）：每页开头带页码标记 `<!-- page N -->`。

- 文字型页：pymupdf4llm 从原文生成，标题、列表、表格都保留。只把部首、兼容表意文字码位换回常用字（见 normalize_radicals），
  合并单元格、被拆错行的表格按单元格结构重新生成（见 _rebuild_tables）。
- OCR 页：按 PP-StructureV3 的版面块生成；表格保留 HTML（能表达合并单元格，分块时不会被拆散）。
- 混合页：原文 + 页内图片的 OCR 结果。
- 跨页表格：上一页最后一块和下一页第一块都是表格、列数相同（或下一页重复了表头）时合并成一张表，
  放在起始页，前面加 `<!-- table pages 3-5 -->` 标明跨了哪几页；重复的表头只保留一次，
  被分页截断的行（续表第一行的第一列为空）接回上一行。
页眉、页脚、页码对知识库检索是噪声，不输出：OCR 页按版面类别跳过，文字型页按各页重复出现的行去掉（strip_running_lines）。
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from html import unescape

import pymupdf
import pymupdf4llm

from docparser.ocr import Block, Result, split_items

SKIP_LABELS = {"header", "footer", "number", "header_image", "footer_image", "aside_text"}
IMAGE_LABELS = {"image", "chart", "seal"}
CAPTION_LABELS = {"figure_title", "table_title", "chart_title", "figure_table_chart_title", "vision_footnote", "footnote"}
IMAGE_NAMES = {"image": "图片", "chart": "图表", "seal": "印章"}


def _clean_table(html: str) -> str:
    html = re.sub(r"</?(html|body)>", "", html)
    return html.replace("<table border=\"1\">", "<table>").strip()


def block_markdown(block: Block) -> str:
    text = block.content.strip()
    label = block.label
    if label in SKIP_LABELS:
        return ""
    if label == "table":
        return _clean_table(text)
    if label in IMAGE_LABELS:
        # 图片本身不输出；图片中识别出的文字（如印章文字）保留，便于检索
        return f"[{IMAGE_NAMES[label]}：{text}]" if text else ""
    if not text:
        return ""
    if label == "doc_title":
        return "# " + text.replace("\n", " ")
    if label == "paragraph_title":
        return "## " + text.replace("\n", " ")
    if label in CAPTION_LABELS:
        return f"*{text}*"
    return "\n\n".join(split_items(text))


def ocr_markdown(result: Result) -> str:
    parts = [block_markdown(b) for b in result.blocks]
    return "\n\n".join(p for p in parts if p)


def text_pages_markdown(doc: pymupdf.Document, page_numbers: list[int]) -> dict[int, str]:
    """page_numbers 从 1 开始；返回 {页码: markdown}。"""
    if not page_numbers:
        return {}
    chunks = pymupdf4llm.to_markdown(
        doc,
        pages=[n - 1 for n in page_numbers],
        page_chunks=True,
        ignore_images=True,
        show_progress=False,
    )
    pages = {}
    for c in chunks:
        # pymupdf4llm 新版本的页码字段是 page_number（从 1 开始），旧版本是 page
        n = c["metadata"].get("page_number") or c["metadata"]["page"]
        text = _rebuild_tables(doc[n - 1], c["text"], c.get("page_boxes") or [])
        pages[n] = _merge_wrapped_rows(_fix_cjk_spaces(normalize_radicals(text)))
    return _apply_toc_headings(pages, doc.get_toc())


def _rebuild_tables(page: pymupdf.Page, text: str, boxes: list[dict]) -> str:
    """pymupdf4llm 拆错结构的表格，按 find_tables 的单元格结构（来自表格线）重新生成 Markdown。

    pymupdf4llm 按文字位置划分表格的行，两种情况会出错：
    - 合并单元格：纵向合并的文字垂直居中在两行之间，「SP-200」里的连字符字形偏低，被分到了下一行
      （变成「SP200」，下一行多出一个「-」）；合并的值只出现在第一行，后面的行是空的；两行表头（「输出功率」
      下分「额定」「峰值」）被拆成「输<br>额定 | 出功率<br>峰值」。
    - 很高的单元格：跨页续表里一个单元格占了大半页，按行距被切成好几行。
    find_tables 按表格线认出每个单元格（被合并覆盖的位置是 None），文字按单词取（同一行的字符不会被拆开）。
    有合并单元格、或行数和 pymupdf4llm 的不一致时，用它重新生成；其余表格不动。
    """
    spans = [b for b in boxes if b.get("class") == "table" and b.get("pos")]
    if not spans:
        return text
    tables = page.find_tables(strategy="lines_strict").tables
    if not tables:
        return text
    words = None
    for box in sorted(spans, key=lambda b: b["pos"][0], reverse=True):
        start, end = box["pos"]
        original = text[start:end]
        if not original.lstrip().startswith("|"):
            continue
        area = pymupdf.Rect(box["bbox"])
        table = next((t for t in tables if abs(pymupdf.Rect(t.bbox) & area) > 0.5 * abs(area)), None)
        if table is None:
            continue
        md_rows = sum(1 for line in original.splitlines() if line.startswith("|") and not _MD_SEPARATOR.match(line.strip()))
        if md_rows == table.row_count and not any(c is None for r in table.rows for c in r.cells):
            continue
        words = words if words is not None else page.get_text("words")
        rebuilt = _table_markdown(table, words)
        if rebuilt:
            text = text[:start] + rebuilt + original[len(original.rstrip()):] + text[end:]
    return text


def _cell_text(rect: tuple, words: list) -> str:
    """单元格里的文字：按单词中心点落在单元格内取，同一文本行的单词用空格连起来，多行之间也用空格
    （中文之间的空格之后由 _fix_cjk_spaces 去掉）。"""
    x0, y0, x1, y1 = rect
    inside = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    inside.sort(key=lambda w: (w[5], w[6], w[7]))  # 块号、行号、单词号：按原文顺序
    return " ".join(w[4] for w in inside).replace("|", "\\|").strip()


def _table_markdown(table, words: list) -> str | None:
    rows = [r.cells for r in table.rows]
    n_rows, n_cols = len(rows), table.col_count
    if n_rows < 2 or any(len(r) != n_cols for r in rows):
        return None
    tops = [r.bbox[1] for r in table.rows]
    lefts = [min((r[c][0] for r in rows if r[c] is not None), default=None) for c in range(n_cols)]
    if None in lefts:
        return None
    grid: list[list[str]] = [[""] * n_cols for _ in range(n_rows)]
    colspan = [[False] * n_cols for _ in range(n_rows)]
    owner: list[list[tuple | None]] = [[None] * n_cols for _ in range(n_rows)]  # 每个位置所属单元格的 bbox
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if cell is not None:
                grid[i][j], owner[i][j] = _cell_text(cell, words), cell
            elif i and owner[i - 1][j] and owner[i - 1][j][3] > tops[i] + 1:  # 上一行的单元格延伸到这一行：纵向合并
                grid[i][j], owner[i][j] = grid[i - 1][j], owner[i - 1][j]
            elif j and owner[i][j - 1] and owner[i][j - 1][2] > lefts[j] + 1:  # 左边的单元格延伸过来：横向合并
                grid[i][j], owner[i][j], colspan[i][j] = grid[i][j - 1], owner[i][j - 1], True
            else:
                return None
    # 表头行数：第一行里纵向跨得最多的单元格跨了几行；只有第一行有横向合并（分组表头）时才按多行表头处理
    depth = 1
    if any(colspan[0]):
        depth = max(sum(1 for t in tops if t < cell[3] - 1) for cell in owner[0])
        depth = depth if 1 < depth < n_rows else 1
    header = []
    for j in range(n_cols):
        parts = []
        for i in range(depth):
            if grid[i][j] and grid[i][j] not in parts:
                parts.append(grid[i][j])
        header.append("/".join(parts))
    body = [[("" if colspan[i][j] else grid[i][j]) for j in range(n_cols)] for i in range(depth, n_rows)]
    lines = ["|" + "|".join(header) + "|", "|" + "---|" * n_cols] + ["|" + "|".join(r) + "|" for r in body]
    return "\n".join(lines)


def _merge_wrapped_rows(text: str) -> str:
    """pymupdf4llm 有时把单元格内自动换行的下半截识别成单独一行（如「|||M12||||」）：
    第一列为空、一半以上单元格为空的行，接回上一行。"""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        prev = out[-1] if out else ""
        if line.startswith("|") and prev.startswith("|") and not _MD_SEPARATOR.match(prev.strip()):
            cells, above = _md_cells(line), _md_cells(prev)
            filled = [c for c in cells if c]
            if len(cells) == len(above) and not cells[0] and filled and len(filled) * 2 <= len(cells):
                out[-1] = "|" + "|".join(_join_cells(above, cells)) + "|"
                continue
        out.append(line)
    return "\n".join(out)


# 有些 PDF 的字体把常用字映射到部首码位：看起来是「车」「用」，实际是康熙部首（U+2F00–2FD5）
# 或部首补充（U+2E80–2EF3）里的另一个字符，检索搜不到。康熙部首用 NFKC 换回常用字；
# 部首补充没有标准分解，按 Unihan 的等价字对照，只收独立成字的（偏旁形式如「⺅」「⻊」不换）
_SUPPLEMENT = dict(zip(
    "⺁⺇⺌⺎⺐⺒⺓⺟⺠⺧⺩⺪⺬⺮⺶⻁⻄⻅⻆⻉⻋⻑⻓⻔⻗⻘⻙⻚⻛⻜⻝⻢⻣⻤⻥⻦⻧⻨⻩⻪⻬⻮⻰⻳",
    "厂几小兀尢巳幺母民牛王疋示竹羊虎西见角贝车長长门雨青韦页风飞食马骨鬼鱼鸟卤麦黄黾齐齿龙龟",
))
# CJK 兼容表意文字（U+F900–FAFF，如「率」U+F9DB）也一样：字体的字形映射到兼容码位，看起来是常用字，检索搜不到。
# 它们有标准分解，NFC 就换回统一码位；该区里本身就是统一表意文字的（如「﨎」U+FA0E）NFC 不变
_COMPAT = {chr(cp): unicodedata.normalize("NFC", chr(cp)) for cp in range(0xF900, 0xFB00)}
_RADICALS = str.maketrans(
    {chr(cp): unicodedata.normalize("NFKC", chr(cp)) for cp in range(0x2F00, 0x2FD6)}
    | _SUPPLEMENT
    | {k: v for k, v in _COMPAT.items() if v != k}
)


def normalize_radicals(text: str) -> str:
    return text.translate(_RADICALS)


def _plain(line: str) -> str:
    return re.sub(r"[\s*_#]+", "", line)


def _apply_toc_headings(pages: dict[int, str], toc: list) -> dict[int, str]:
    """用 PDF 书签还原标题层级：Word 转出的 PDF 带有标题书签，pymupdf4llm 按字号判断时常常只识别成粗体。
    书签所在页中，内容和书签标题完全一致的行改成对应级别的标题。"""
    for level, title, page in toc:
        if page not in pages or not _plain(title):
            continue
        lines = pages[page].split("\n")
        for i, line in enumerate(lines):
            if _plain(line) == _plain(title):
                lines[i] = "#" * min(level, 6) + " " + title.strip()
                break
        pages[page] = "\n".join(lines)
    return pages


CJK = r"\u3000-\u303f\u3400-\u9fff\uff00-\uffef"
# pymupdf4llm 把排版换行拼成空格，中文词会被拆开（如「标 准」）；删掉两个中文字符之间的空格
_CJK_SPACE = re.compile(rf"(?<=[{CJK}]) +(?=[{CJK}])")


# 表格单元格内自动换行被输出成 <br>：中文之间直接拼接，其他情况换成空格
_CJK_BR = re.compile(rf"(?<=[{CJK}])<br>(?=[{CJK}])")


def _fix_cjk_spaces(text: str) -> str:
    lines = []
    for line in text.strip().splitlines():
        if line.startswith("|"):
            line = _CJK_BR.sub("", line).replace("<br>", " ")
        lines.append(_CJK_SPACE.sub("", line).rstrip())
    return "\n".join(lines)


def build(page_markdown: dict[int, str]) -> str:
    parts = []
    for number in sorted(page_markdown):
        body = page_markdown[number].strip()
        parts.append(f"<!-- page {number} -->\n\n{body}" if body else f"<!-- page {number} -->")
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------- 页眉页脚

_EDGE_BLOCKS = 2  # 每页开头、结尾各看几块
_RUNNING_MAX_CHARS = 60
# 页眉页脚里随页变化的页码：「第 3 页」「共 10 页」「Page 3」「3/10」「- 3 -」「手册 · 3」。
# 只统一这些形式，「小计 300」这类每页数字不同的正文不会被当成页脚
_RUNNING_PAGE_NO = re.compile(
    r"第\s*\d+\s*页|共\s*\d+\s*页|page\s*\d+|\d+\s*/\s*\d+|-\s*\d+\s*-|^\d+\s*[·|]|[·|]\s*\d+$", re.I
)


def _running_key(block: str) -> str | None:
    """页眉页脚候选的比较键：页码统一成 #，再去掉空白和 Markdown 标记。
    表格、标题、长段落和只有数字的行（页码另外处理）不算。"""
    if block.startswith(("|", "<", "#")):
        return None
    plain = re.sub(r"[\s*_>`]+", "", _RUNNING_PAGE_NO.sub("#", block.strip()))
    if not plain or len(plain) > _RUNNING_MAX_CHARS or not re.search(r"[^\W\d_]", plain):
        return None
    return plain


def _edges(blocks: list[str]) -> set[int]:
    return set(range(min(_EDGE_BLOCKS, len(blocks)))) | set(range(max(len(blocks) - _EDGE_BLOCKS, 0), len(blocks)))


def strip_running_lines(page_markdown: dict[int, str]) -> tuple[dict[int, str], list[str]]:
    """去掉页眉页脚：每页开头、结尾两块之内，在一半以上有内容的页面（至少 2 页）重复出现的短文字。
    返回（新的每页 Markdown，去掉的文字）。

    文字型页的页眉页脚就是普通文字，不去掉的话每页都多一个只有页眉的分段，问题里出现手册名、
    产品系列名时这些分段会排到检索结果最前面。要在跨页表格合并之前做：页眉夹在两页表格之间会挡住合并。
    """
    blocks = {n: _split_blocks(md) for n, md in page_markdown.items()}
    pages = [n for n, b in blocks.items() if b]
    if len(pages) < 2:
        return page_markdown, []
    counts: Counter[str] = Counter()
    for n in pages:
        counts.update({k for i in _edges(blocks[n]) if (k := _running_key(blocks[n][i]))})
    running = {k for k, c in counts.items() if c >= max(2, (len(pages) + 1) // 2)}
    if not running:
        return page_markdown, []
    out, removed = {}, {}
    for n, page_blocks in blocks.items():
        drop = {i for i in _edges(page_blocks) if _running_key(page_blocks[i]) in running}
        for i in sorted(drop):
            removed.setdefault(_running_key(page_blocks[i]), page_blocks[i])
        out[n] = "\n\n".join(b for i, b in enumerate(page_blocks) if i not in drop)
    return out, list(removed.values())


def _split_blocks(md: str) -> list[str]:
    return [b for b in re.split(r"\n\s*\n", md.strip()) if b.strip()]


# ---------------------------------------------------------------- 跨页表格

# 页码行（文字型页的页脚可能带页码）：判断「上一页最后一块 / 下一页第一块」时跳过
_PAGE_NUMBER = re.compile(
    r"^\s*(第\s*\d+\s*页(\s*[/，,]?\s*共\s*\d+\s*页)?|[-—–\s]*\d+[-—–\s]*|\d+\s*/\s*\d+|page\s+\d+(\s+of\s+\d+)?)\s*$",
    re.I,
)
_ANNOTATION = re.compile(r"^<!-- table pages (\d+)-(\d+) -->\n")
_TR = re.compile(r"<tr[^>]*>.*?</tr>", re.S | re.I)
_TD = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.S | re.I)
_COLSPAN = re.compile(r"colspan\s*=\s*[\"']?(\d+)", re.I)
_MD_SEPARATOR = re.compile(r"^\|?(\s*:?-{3,}:?\s*\|)+\s*:?-*:?\s*$")


@dataclass
class _Table:
    kind: str  # md / html
    rows: list[list[str]]  # 每行的单元格文字（去掉空白和标签，用于比较表头）
    width: int  # 列数（含 colspan）
    raw_rows: list[str]  # 原始行：HTML 的 <tr>…</tr>，或 Markdown 的表头行和数据行（不含分隔行）


def _norm(cell: str) -> str:
    return re.sub(r"\s+", "", unescape(re.sub(r"<[^>]+>", "", cell)))


def _md_cells(line: str) -> list[str]:
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") else line  # 只去掉首尾各一个竖线：第一列为空时是「||…」
    return [c.strip() for c in line.split("|")]


def _parse_table(block: str) -> _Table | None:
    body = _ANNOTATION.sub("", block.strip())
    if body.lower().startswith("<table") and body.lower().endswith("</table>"):
        rows, raw, width = [], [], 0
        for tr in _TR.findall(body):
            cells = _TD.findall(tr)
            rows.append([_norm(c) for _, c in cells])
            raw.append(tr)
            width = max(width, sum(int(m.group(1)) if (m := _COLSPAN.search(a)) else 1 for a, _ in cells))
        return _Table("html", rows, width, raw) if rows else None
    lines = body.splitlines()
    if len(lines) >= 2 and all(line.lstrip().startswith("|") for line in lines) and _MD_SEPARATOR.match(lines[1].strip()):
        data = [lines[0]] + lines[2:]
        rows = [[_norm(c) for c in _md_cells(line)] for line in data]
        return _Table("md", rows, max(len(r) for r in rows), data)
    return None


def _md_row_html(line: str, tag: str = "td") -> str:
    return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in _md_cells(line)) + "</tr>"


def _join_cells(a: list[str], b: list[str]) -> list[str]:
    """逐列拼接被截断的单元格：两边都是中文时直接连起来，否则中间加空格（和 <br> 的处理一致）。"""
    return [(x + y) if re.search(rf"[{CJK}]$", x) and re.match(rf"[{CJK}]", y) else f"{x} {y}".strip() for x, y in zip(a, b)]


def _merge_split_row(first_block: str, first: _Table, second: _Table, extra: list[str]) -> tuple[str, list[str]]:
    """一行被分页截断（Word 默认「允许跨页断行」）：续表第一行的第一列为空、列数和上一行相同，
    把它的各列内容接到上一页最后一行。返回（更新后的第一张表，剩下的续表行）。"""
    if not extra or len(first.raw_rows) < 2:
        return first_block, extra
    if second.kind == "md":
        cont = _md_cells(extra[0])
    else:
        cont = [c for _, c in _TD.findall(extra[0])]
    if first.kind == "md":
        last = _md_cells(first.raw_rows[-1])
    else:
        last = [c for _, c in _TD.findall(first.raw_rows[-1])]
    if len(cont) != len(last) or _norm(cont[0]) or not any(_norm(c) for c in cont[1:]):
        return first_block, extra
    joined = _join_cells([c.strip() for c in last], [c.strip() for c in cont])
    old_row = first.raw_rows[-1]
    new_row = "|" + "|".join(joined) + "|" if first.kind == "md" else "<tr>" + "".join(f"<td>{c}</td>" for c in joined) + "</tr>"
    head, sep, tail = first_block.rpartition(old_row)
    first.raw_rows[-1] = new_row
    return head + new_row + tail, extra[1:]


def _merge(first_block: str, first: _Table, second: _Table) -> str:
    """把 second 的行接到 first 后面；second 重复了表头时去掉，被分页截断的行接回上一行。
    两边都是 Markdown 表格时输出 Markdown，否则输出 HTML。"""
    extra = second.raw_rows[1:] if second.rows[0] == first.rows[0] else second.raw_rows
    first_block, extra = _merge_split_row(first_block, first, second, extra)
    body = _ANNOTATION.sub("", first_block.strip())
    if first.kind == "md" and second.kind == "md":
        return body + ("\n" + "\n".join(extra) if extra else "")
    if first.kind == "md":
        body = "<table>" + _md_row_html(first.raw_rows[0], "th") + "".join(_md_row_html(r) for r in first.raw_rows[1:]) + "</table>"
    rows = "".join(r if second.kind == "html" else _md_row_html(r) for r in extra)
    return body[: body.lower().rfind("</table>")] + rows + "</table>"


def _content_indexes(blocks: list[str]) -> list[int]:
    return [i for i, b in enumerate(blocks) if not _PAGE_NUMBER.match(b)]


def merge_cross_page_tables(page_markdown: dict[int, str]) -> tuple[dict[int, str], list[dict]]:
    """合并跨页表格。返回（新的每页 Markdown，合并记录 [{"pages": "3-5", "rows": 行数}]）。

    判断规则：第 N 页最后一块是表格，第 N+1 页第一块也是表格（页码行不算），并且列数相同，
    或者第 N+1 页的表格第一行和表头相同（Word「重复标题行」、扫描件每页都印表头）。
    合并后第 N+1 页如果只剩这张表，表格可能继续延伸到第 N+2 页。
    """
    blocks = {n: _split_blocks(md) for n, md in page_markdown.items()}
    open_table: tuple[int, int, int] | None = None  # （所在页，块序号，起始页）
    previous = None
    for n in sorted(blocks):
        page_blocks = blocks[n]
        content = _content_indexes(page_blocks)
        if open_table and previous == n - 1 and content:
            page, index, start = open_table
            first = _parse_table(blocks[page][index])
            second = _parse_table(page_blocks[content[0]])
            if first and second and (first.width == second.width or second.rows[0] == first.rows[0]):
                merged = _merge(blocks[page][index], first, second)
                blocks[page][index] = f"<!-- table pages {start}-{n} -->\n{merged}"
                del page_blocks[content[0]]
                content = _content_indexes(page_blocks)
                if not content:  # 这一页只有这张表的续表
                    previous = n
                    continue
        last = content[-1] if content else None
        open_table = (n, last, n) if last is not None and _parse_table(page_blocks[last]) else None
        previous = n

    merged_tables = []
    for page_blocks in blocks.values():
        for block in page_blocks:
            if m := _ANNOTATION.match(block):
                table = _parse_table(block)
                merged_tables.append({"pages": f"{m.group(1)}-{m.group(2)}", "rows": len(table.rows) if table else 0})
    return {n: "\n\n".join(_strip_page_numbers(b)) for n, b in blocks.items()}, merged_tables


def _strip_page_numbers(blocks: list[str]) -> list[str]:
    """去掉每页开头、结尾的页码行（文字型页的页眉页脚）。正文中间单独的数字不动。

    不去掉的话，表格跨页合并后续页只剩一行「- 2 -」，知识库里会多出只有页码的分段。
    """
    start, end = 0, len(blocks)
    while start < end and _PAGE_NUMBER.match(blocks[start]):
        start += 1
    while end > start and _PAGE_NUMBER.match(blocks[end - 1]):
        end -= 1
    return blocks[start:end]
