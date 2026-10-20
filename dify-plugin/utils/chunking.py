"""按页分段：把带页码标记的 Markdown 切成知识库分段，每段开头注明页码和所在章节。

通用分块器只按分隔符切分，不会合并短段落：页码标记会单独成为一段，正文分段里没有页码。
这里按页、按段落合并到不超过 max_chars，标题开始新的分段，
每段以「【文档名 · 第 N 页 · 章节标题】」开头（英文是 "[name · p. N · section]"），检索到任何一段都能引用页码。
文档名用来区分内容相近的文档（如同一手册的新旧版本）：知识库检索交给模型的只有分段内容，没有文件名。
HTML 表格转成纯文本表格，避免标签占用关键词索引的名额。

表格：
- 跨页表格（服务端已合并，前面有 `<!-- table pages 3-5 -->`）单独成段，标注「第 3–5 页」。
- 表格的上限是 table_max_chars（默认等于 max_chars，不能小于 max_chars）：不超过上限的表格不拆开，
  超长的表格按行切开，每段都带上表头，检索到任何一段都知道各列的含义。
  把 table_max_chars 设得比 max_chars 大（如 3000），中小表格就能整张放进一个分段，同时超大表格仍有上限。
"""

from __future__ import annotations

import re
from html import unescape

from utils.i18n import DEFAULT_LANGUAGE, page_label

PAGE_MARKER = re.compile(r"^<!-- page (\d+) -->\s*$", re.MULTILINE)
TABLE_PAGES = re.compile(r"^<!-- table pages (\d+)-(\d+) -->\n")
MD_SEPARATOR = re.compile(r"^\|?(\s*:?-{3,}:?\s*\|)+")
SENTENCE_END = re.compile(r"(?<=[。！？；!?;])")

DEFAULT_CHUNK_CHARS = 800


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def limits(params: dict) -> tuple[int, int]:
    """从工具参数得到（分段最大字数，表格最大字数）。分段最大字数最少 200。

    表格最大字数为 0 时与分段最大字数相同。
    """
    max_chars = max(_int(params.get("chunk_max_chars")) or DEFAULT_CHUNK_CHARS, 200)
    return max_chars, _int(params.get("table_max_chars"))


def split_pages(markdown: str) -> list[tuple[int, str]]:
    """按 <!-- page N --> 切分，返回 [(页码, 内容)]；没有页码标记时整篇作为第 1 页。"""
    parts = PAGE_MARKER.split(markdown)
    if len(parts) == 1:
        return [(1, markdown)]
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")


def html_table_to_text(html: str) -> str:
    """HTML 表格转成「| 单元格 | 单元格 |」：关键词索引不会再把 td、tr 当成关键词，模型也能直接读。"""
    lines = []
    for row in _ROW.findall(html):
        cells = [unescape(_TAG.sub("", c)).strip().replace("|", "/") for c in _CELL.findall(row)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) if lines else html


def split_table(text: str, max_chars: int) -> list[str]:
    """超长表格按行切开，每段都以表头开头（Markdown 表格的表头包括分隔行）。"""
    if len(text) <= max_chars:
        return [text]
    lines = text.splitlines()
    head = lines[:2] if len(lines) > 1 and MD_SEPARATOR.match(lines[1].strip()) else lines[:1]
    pieces, current = [], []
    for row in lines[len(head):]:
        if current and sum(len(x) + 1 for x in head + current) + len(row) > max_chars:
            pieces.append("\n".join(head + current))
            current = []
        current.append(row)
    if current:
        pieces.append("\n".join(head + current))
    return pieces


def _is_table(text: str) -> bool:
    return text.startswith(("<table", "|"))


def _split_long(text: str, max_chars: int, table_max_chars: int) -> list[str]:
    """超长段落按句子切分，单句仍超长时硬切。表格超过 table_max_chars 时按行切分。"""
    if _is_table(text):
        return split_table(text, table_max_chars)
    if len(text) <= max_chars:
        return [text]
    pieces, current = [], ""
    for sentence in SENTENCE_END.split(text):
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + len(sentence) > max_chars:
            pieces.append(current)
            current = ""
        current += sentence
    if current:
        pieces.append(current)
    return pieces


def doc_label(filename: str | None) -> str:
    """分段标注里的文档名：去掉扩展名（以字母开头，「报告 2026.10」不算），【】和换行换成空格。"""
    stem = re.sub(r"\.[A-Za-z][A-Za-z0-9]{0,4}$", "", (filename or "").strip())
    return re.sub(r"[【】\s]+", " ", stem).strip()


def chunk_markdown(
    markdown: str, max_chars: int = 800, table_max_chars: int = 0, doc_name: str = "", lang: str = DEFAULT_LANGUAGE
) -> list[str]:
    table_max_chars = max(table_max_chars, max_chars)
    chunks: list[str] = []
    heading = ""  # 当前章节标题，跨页延续

    for page, body in split_pages(markdown):
        current: list[str] = []
        current_heading = heading

        def flush(pages: str = ""):
            if not current:
                return
            text = "\n\n".join(current)
            label = page_label(str(pages or page), lang)
            if doc_name:
                label = f"{doc_name} · {label}"
            # 分段本身以标题开头时不重复章节名
            if current_heading and not current[0].startswith("#"):
                label += f" · {current_heading}"
            chunks.append(f"【{label}】\n{text}" if lang == "zh" else f"[{label}]\n{text}")
            current.clear()

        for block in (b.strip() for b in body.split("\n\n")):
            if not block:
                continue
            span = TABLE_PAGES.match(block)
            if span:
                # 跨页表格单独成段（按行切开时每段都带表头），标注起止页
                flush()
                current_heading = heading
                table = block[span.end():].strip()
                table = html_table_to_text(table) if table.startswith("<table") else table
                for piece in split_table(table, table_max_chars):
                    current.append(piece)
                    flush(f"{span.group(1)}–{span.group(2)}")
                continue
            if block.startswith("<table"):
                block = html_table_to_text(block)
            if block.startswith("#"):
                flush()
                heading = current_heading = block.lstrip("#").strip()
                current.append(block)
                continue
            for piece in _split_long(block, max_chars, table_max_chars):
                if current and sum(len(c) for c in current) + len(piece) > max_chars:
                    flush()
                    current_heading = heading
                current.append(piece)
        flush()
    return chunks
