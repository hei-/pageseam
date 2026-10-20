"""分段规则：「分段最大字数」（max_chars）和「表格最大字数」（table_max_chars）一起用时的效果。

用法（在 dify-plugin 目录）: python3 -m unittest discover tests
只依赖标准库；tests/ 在 .difyignore 中，不会打进插件包。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.chunking import chunk_markdown, doc_label, limits  # noqa: E402

MAX = 300
TABLE_MAX = 1500
HEADER = "| 物料编码 | 名称 | 单价 |\n| --- | --- | --- |"


def table(rows: int, start: int = 0) -> str:
    return HEADER + "\n" + "\n".join(f"| WL-{i:04d} | 物料{i} | {i}.00 |" for i in range(start, start + rows))


def body(chunk: str) -> str:
    """去掉「【第 N 页 · 章节】」标注，只看内容。"""
    return chunk.split("\n", 1)[1]


PARAGRAPH = "本合同条款适用于双方的全部交易。" * 5  # 80 字
LONG_PARAGRAPH = "乙方应按期交货并提供售后服务。" * 40  # 600 字，超过 MAX
MEDIUM, LARGE = table(30), table(100)  # 约 850 字（MAX 和 TABLE_MAX 之间）、约 2900 字（超过 TABLE_MAX）


class ChunkingTest(unittest.TestCase):
    def assert_table_rows(self, chunks, rows):
        """所有分段里的数据行合起来正好是 rows 行，不重复不遗漏。"""
        found = [line for c in chunks for line in c.splitlines() if line.startswith("| WL-")]
        self.assertEqual(sorted(found), sorted(table(rows).splitlines()[2:]))

    def assert_split_with_header(self, chunks, limit):
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(body(c)), limit)
            self.assertTrue(body(c).startswith(HEADER))

    def test_default_table_limit_is_max_chars(self):
        """默认（table_max_chars=0）：表格超过分段最大字数就按行切开，每段都以表头开头。"""
        self.assertTrue(MAX < len(MEDIUM) < TABLE_MAX < len(LARGE))
        chunks = chunk_markdown(f"<!-- page 1 -->\n{MEDIUM}\n", MAX)
        self.assert_split_with_header(chunks, MAX)
        self.assert_table_rows(chunks, 30)

    def test_table_limit_below_max_chars_ignored(self):
        """表格最大字数小于分段最大字数时，按分段最大字数算。"""
        md = f"<!-- page 1 -->\n{MEDIUM}\n"
        self.assertEqual(chunk_markdown(md, MAX, 100), chunk_markdown(md, MAX))

    def test_medium_table_whole(self):
        """表格在两个上限之间：整张放进一个分段，表头只有一行。"""
        chunks = chunk_markdown(f"<!-- page 1 -->\n{MEDIUM}\n", MAX, TABLE_MAX)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(body(chunks[0]).count("物料编码"), 1)
        self.assert_table_rows(chunks, 30)

    def test_large_table_split_at_table_limit(self):
        """表格超过表格最大字数：按行切开，每段不超过表格最大字数，都带表头。"""
        chunks = chunk_markdown(f"<!-- page 1 -->\n{LARGE}\n", MAX, TABLE_MAX)
        self.assert_split_with_header(chunks, TABLE_MAX)
        self.assertTrue(any(len(body(c)) > MAX for c in chunks))
        self.assert_table_rows(chunks, 100)

    def test_text_limited_by_max_chars(self):
        """正文只受分段最大字数限制，与表格最大字数无关：超长段落按句子切开。"""
        md = f"<!-- page 1 -->\n{LONG_PARAGRAPH}\n\n{MEDIUM}\n\n{LONG_PARAGRAPH}\n"
        for table_max in (0, TABLE_MAX):
            chunks = chunk_markdown(md, MAX, table_max)
            text = [c for c in chunks if "| WL-" not in c]
            self.assertGreaterEqual(len(text), 4)
            for c in text:
                self.assertLessEqual(len(body(c)), MAX)

    def test_whole_table_gets_own_chunk(self):
        """超过分段最大字数的整张表格自己一段，前后的正文在别的分段。"""
        md = f"<!-- page 1 -->\n{PARAGRAPH}\n\n{MEDIUM}\n\n{PARAGRAPH}\n"
        chunks = chunk_markdown(md, MAX, TABLE_MAX)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(body(chunks[1]).startswith(HEADER))
        self.assertNotIn("| WL-", chunks[0] + chunks[2])

    def test_short_table_shares_chunk(self):
        """不超过分段最大字数的表格可以和前后正文放在同一段。"""
        md = f"<!-- page 1 -->\n{PARAGRAPH}\n\n{table(3)}\n"
        for table_max in (0, TABLE_MAX):
            chunks = chunk_markdown(md, MAX, table_max)
            self.assertEqual(len(chunks), 1)
            self.assertIn(PARAGRAPH, chunks[0])
            self.assertIn("| WL-0002 |", chunks[0])

    def test_cross_page_table(self):
        """跨页表格总是单独成段，标注起止页，同样受表格最大字数限制。"""
        def tables(rows, table_max):
            md = (f"<!-- page 1 -->\n{PARAGRAPH}\n\n<!-- table pages 1-2 -->\n{table(rows)}\n"
                  f"<!-- page 2 -->\n{PARAGRAPH}\n")
            found = [c for c in chunk_markdown(md, MAX, table_max) if "| WL-" in c]
            for c in found:
                self.assertTrue(c.startswith("【第 1–2 页】"))
                self.assertNotIn(PARAGRAPH, c)
            self.assert_table_rows(found, rows)
            return found

        self.assert_split_with_header(tables(30, 0), MAX)
        self.assertEqual(len(tables(30, TABLE_MAX)), 1)
        self.assert_split_with_header(tables(100, TABLE_MAX), TABLE_MAX)

    def test_short_cross_page_table_still_alone(self):
        """跨页表格即使很短，也不和正文放在同一段。"""
        md = f"<!-- page 1 -->\n{PARAGRAPH}\n\n<!-- table pages 1-2 -->\n{table(3)}\n<!-- page 2 -->\n{PARAGRAPH}\n"
        chunks = chunk_markdown(md, MAX)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(chunks[1].startswith("【第 1–2 页】"))


class LimitsTest(unittest.TestCase):
    """工具参数 → （分段最大字数，表格最大字数）。"""

    def test_doc_name_in_label(self):
        """文档名放在每段标注的最前面，跨页表格同样标注；不传文档名时只标注页码。"""
        md = f"<!-- page 1 -->\n# 充电\n\n{PARAGRAPH}\n<!-- page 2 -->\n<!-- table pages 2-3 -->\n{table(3)}\n"
        chunks = chunk_markdown(md, MAX, 0, "手册 v2.1")
        self.assertEqual([c.split("\n", 1)[0] for c in chunks], ["【手册 v2.1 · 第 1 页】", "【手册 v2.1 · 第 2–3 页 · 充电】"])
        self.assertEqual([body(c) for c in chunks], [body(c) for c in chunk_markdown(md, MAX)])
        self.assertTrue(chunk_markdown(md, MAX)[0].startswith("【第 1 页】"))

    def test_doc_label(self):
        self.assertEqual(doc_label("version_manual_v2_1.pdf"), "version_manual_v2_1")
        self.assertEqual(doc_label("采购合同【终版】.docx"), "采购合同 终版")
        self.assertEqual(doc_label("报告 2026.10"), "报告 2026.10")
        self.assertEqual(doc_label(None), "")

    def test_defaults(self):
        self.assertEqual(limits({}), (800, 0))
        self.assertEqual(limits({"chunk_max_chars": 100}), (200, 0))  # 最少 200
        self.assertEqual(limits({"chunk_max_chars": "500", "table_max_chars": "2000"}), (500, 2000))


if __name__ == "__main__":
    unittest.main()
