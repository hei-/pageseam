"""端到端检查：跨页表格合并、Word（doc / docx）转换和其中扫描图片的识别。

用法（在服务镜像中执行）: python tests/check_tables.py <make_tables_sample.py 的输出目录> <工作目录>
会先用 LibreOffice 把 office.docx 另存为 office.doc，所有文件都走完整流程。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from docparser import config, pipeline  # noqa: E402

failures = []


def check(ok: bool, message: str) -> None:
    print(("✅ " if ok else "❌ ") + message)
    if not ok:
        failures.append(message)


def run(src: str, work: str, outputs: list[str], **extra) -> tuple[dict, str]:
    job_dir = os.path.join(work, os.path.basename(src).replace(".", "_") + "".join(f"_{v}" for v in extra.values()))
    shutil.rmtree(job_dir, ignore_errors=True)
    os.makedirs(job_dir)
    ext = os.path.splitext(src)[1].lower()
    options = {"outputs": outputs, "ocr": "auto", "word_images": "replace", **extra}
    if ext == ".pdf":
        shutil.copy(src, os.path.join(job_dir, "input.pdf"))
        import pymupdf

        with pymupdf.open(src) as doc:
            options.update(pages=list(range(1, doc.page_count + 1)), ocr_pages=[])
    else:
        shutil.copy(src, os.path.join(job_dir, "input" + ext))
        options.update(source_type=ext.lstrip("."), pages_spec="", ocr_pages_spec="")
    start = time.time()
    result = pipeline.run(job_dir, options)
    md = ""
    if "markdown" in outputs:
        with open(os.path.join(job_dir, "result.md"), encoding="utf-8") as f:
            md = f.read()
    result["dir"] = job_dir
    print(f"\n== {os.path.basename(src)}：{result['page_count']} 页，{time.time() - start:.0f} 秒，"
          f"{json.dumps(result['summary'], ensure_ascii=False)}")
    return result, md


def word_tables(job_dir: str) -> list[tuple[int, bool, list[str]]]:
    """Word 输出中的表格：（行数，首行是否为重复标题行，每行文字）。"""
    from docx import Document
    from docx.oxml.ns import qn

    out = []
    for table in Document(os.path.join(job_dir, "result.docx")).tables:
        tr_pr = table._tbl.findall(qn("w:tr"))[0].find(qn("w:trPr"))
        header = tr_pr is not None and tr_pr.find(qn("w:tblHeader")) is not None
        out.append((len(table.rows), header, ["".join(c.text for c in r.cells).replace(" ", "") for r in table.rows]))
    return out


def merged_table(md: str, pages: str) -> str:
    m = re.search(rf"<!-- table pages {pages} -->\n(.*?)(?=\n\n|\Z)", md, re.S)
    return m.group(1) if m else ""


def main(sample_dir: str, work: str) -> None:
    os.makedirs(work, exist_ok=True)
    # docx 另存为 doc（旧版 Word 格式）
    subprocess.run([config.LIBREOFFICE, "--headless", f"-env:UserInstallation=file://{work}/lo-profile",
                    "--convert-to", "doc", "--outdir", sample_dir, os.path.join(sample_dir, "office.docx")],
                   check=True, capture_output=True, timeout=180)

    # ---------- PDF：文字型页和扫描页的跨页表格 ----------
    result, md = run(os.path.join(sample_dir, "tables.pdf"), work, ["markdown"])
    tables = {t["pages"]: t["rows"] for t in result["summary"]["cross_page_tables"]}
    check(tables.get("1-2") == 37, f"文字型页物料清单合并为一张表，表头 1 行 + 36 行（实际 {tables.get('1-2')}）")
    t12 = merged_table(md, "1-2")
    check(len(re.findall(r"物料编码", t12)) == 1, "第 2 页重复的表头只保留一次")
    check("WL-1000" in t12 and "WL-1035" in t12 and "5,600.00" in t12, "首行、末行和第 2 页的行都在合并后的表中")
    check(tables.get("3-4") == 21, f"扫描页验收记录合并为一张表，表头 1 行 + 20 行（实际 {tables.get('3-4')}）")
    t34 = merged_table(md, "3-4")
    check("外观检查" in t34 and "连续试运行72小时" in t34.replace(" ", ""), "扫描表格的首行和第 4 页最后一行都在")
    check(not any(p.endswith("-5") for p in tables), "第 5 页列数不同的表格没有被合并")
    check("400-820-6688" in md.split("<!-- page 5 -->")[1], "第 5 页的表格仍在第 5 页")

    # ---------- Word：docx 和 doc ----------
    for name in ("office.docx", "office.doc"):
        result, md = run(os.path.join(sample_dir, name), work, ["markdown", "pdf", "docx"])
        summary = result["summary"]
        check(summary.get("converted_from") == name.split(".")[1], f"{name} 先转换为 PDF")
        rows = [t["rows"] for t in summary["cross_page_tables"]]
        check(37 in rows, f"{name}：跨页的长表格合并为一张表，表头 1 行 + 36 行（实际 {summary['cross_page_tables']}）")
        flat = md.replace(" ", "")
        check("WL-1035" in flat and "年度维保服务" in flat, f"{name}：原生文字和表格内容完整")
        check("2026-10-25" in flat and "甲方计量室" in flat, f"{name}：嵌入的扫描图片（交付计划表）已识别")
        check("400-820-6688" in flat and "备品备件" in flat, f"{name}：整页扫描图片（售后服务承诺）已识别")
        check(set(result["files"]) == {"markdown", "pdf", "docx"}, f"{name}：三种输出都生成了")

    # ---------- Word：一行被分页截断 ----------
    result, md = run(os.path.join(sample_dir, "clauses.docx"), work, ["markdown"])
    tables = {t["pages"]: t["rows"] for t in result["summary"]["cross_page_tables"]}
    check(tables.get("1-2") == 17, f"条款表合并为一张表，表头 1 行 + 16 行（实际 {tables.get('1-2')}）")
    row = next((line for line in md.splitlines() if "违约责任" in line), "").replace(" ", "")
    check("第8款" in row and "第9款" in row and "百分之十" in row, "被分页截断的「违约责任」一行接回成一行")

    # ---------- 续页没有表头：文字型 PDF、Word（未设置重复标题行），都跨 3 页 ----------
    for name in ("noheader.pdf", "noheader.docx"):
        result, md = run(os.path.join(sample_dir, name), work, ["markdown", "docx"], word_tables="merge")
        tables = result["summary"]["cross_page_tables"]
        check(len(tables) == 1 and tables[0]["rows"] == 91, f"{name}：跨 3 页、续页无表头的表格合并为一张，表头 1 行 + 90 行（实际 {tables}）")
        body = merged_table(md, tables[0]["pages"]) if tables else ""
        check(body.count("物料编码") == 1 and "WL-2000" in body and "WL-2089" in body, f"{name}：表头只有一行，首行和末行都在")
        rows = [t[0] for t in word_tables(result["dir"])]
        check(rows == [91], f"{name}：Word 输出合并成一张表（实际行数 {rows}）")

    # ---------- Word 输出中的跨页表格：默认 keep，可选 merge ----------
    result, _ = run(os.path.join(sample_dir, "tables.pdf"), work, ["docx"])
    rows = [t[0] for t in word_tables(result["dir"])]
    check(rows == [27, 11, 13, 8, 2], f"word_tables=keep：和原件分页一致，每页一张表（实际行数 {rows}）")
    result, _ = run(os.path.join(sample_dir, "tables.pdf"), work, ["docx"], word_tables="merge")
    tables = word_tables(result["dir"])
    check([t[0] for t in tables] == [37, 21, 2], f"word_tables=merge：两张跨页表格各合并成一张，列数不同的表不合并（实际行数 {[t[0] for t in tables]}）")
    check(tables[0][1] and tables[1][1], "合并后的表格首行设为重复标题行")
    check(sum("物料编码" in r for r in tables[0][2]) == 1, "重复的表头只保留一次")
    result, _ = run(os.path.join(sample_dir, "clauses.docx"), work, ["docx"], word_tables="merge")
    tables = word_tables(result["dir"])
    row = next((r for r in tables[0][2] if "违约责任" in r), "")
    check(tables[0][0] == 17 and "第8款：乙方逾期交货的" in row and "百分之十" in row, "Word 中被分页截断的一行接回成一行")

    print(f"\n{'全部通过' if not failures else f'{len(failures)} 项失败'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
