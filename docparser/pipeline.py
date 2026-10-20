"""一个任务的完整处理流程（在工作进程中执行）。

（Office 文档先转成 PDF）→ 分类 → 需要 OCR 的页或区域逐个识别（只识别一次，三种输出共用）
→ 生成 Markdown（跨页表格合并）/ 可搜索 PDF / Word。
"""

import json
import os
import time

import pymupdf

from docparser import classify, config, convert, i18n, markdown, ocr, searchable_pdf, word
from docparser.classify import BLANK, MIXED

OUTPUT_FILES = {"markdown": "result.md", "pdf": "result.pdf", "docx": "result.docx"}


class Progress:
    def __init__(self, job_dir: str):
        self.path = os.path.join(job_dir, "progress.json")
        self.started_at = time.time()

    def __call__(self, stage: str, done: int = 0, total: int = 0) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"stage": stage, "done": done, "total": total, "started_at": self.started_at}, f, ensure_ascii=False)
        os.replace(tmp, self.path)


def _prepare_office(job_dir: str, options: dict, progress: Progress) -> None:
    """Office 文档转成 input.pdf，再按转换后的页数解析页码范围。"""
    lang = options.get("lang")
    progress(i18n.t("stage.convert", lang))
    source = os.path.join(job_dir, "input." + options["source_type"])
    convert.to_pdf(source, os.path.join(job_dir, "input.pdf"), lang)
    os.unlink(source)
    with pymupdf.open(os.path.join(job_dir, "input.pdf")) as doc:
        page_count = doc.page_count
    try:
        selected = classify.parse_page_ranges(options.get("pages_spec", ""), page_count) or set(range(1, page_count + 1))
        options["ocr_pages"] = sorted(classify.parse_page_ranges(options.get("ocr_pages_spec", ""), page_count))
    except classify.PageRangeError as e:
        raise ValueError(i18n.t("bad_page_range", lang, part=e.part)) from None
    if len(selected) > config.MAX_PAGES:
        raise ValueError(i18n.t("too_many_pages", lang, pages=len(selected), limit=config.MAX_PAGES))
    options["pages"] = sorted(selected)


def run(job_dir: str, options: dict) -> dict:
    progress = Progress(job_dir)
    lang = options.get("lang")
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    if options.get("source_type"):
        _prepare_office(job_dir, options, progress)
        timings["convert"] = time.perf_counter() - t0
    progress(i18n.t("stage.classify", lang))
    t = time.perf_counter()

    src_path = os.path.join(job_dir, "input.pdf")
    src = pymupdf.open(src_path)
    selected = set(options["pages"])
    infos = [
        info
        for info in classify.classify_document(src, options["ocr"], set(options["ocr_pages"]), config.CLASSIFY, lang)
        if info.page in selected
    ]
    timings["classify"] = time.perf_counter() - t

    # ---------- OCR ----------
    todo = [i for i in infos if i.full_ocr or i.kind == MIXED]
    results: dict[int, list[ocr.Result]] = {}
    page_seconds: dict[int, float] = {}
    t = time.perf_counter()
    for n, info in enumerate(todo):
        progress(i18n.t("stage.ocr", lang), n, len(todo))
        start = time.perf_counter()
        page = src[info.page - 1]
        if info.full_ocr:
            results[info.page] = [ocr.recognize(page)]
        else:
            results[info.page] = [ocr.recognize(page, clip=pymupdf.Rect(r)) for r in info.ocr_regions]
        page_seconds[info.page] = time.perf_counter() - start
    timings["ocr"] = time.perf_counter() - t

    # ---------- 输出 ----------
    outputs = options["outputs"]
    if "markdown" in outputs:
        progress(i18n.t("stage.markdown", lang))
        t = time.perf_counter()
        text_pages = [i.page for i in infos if not i.full_ocr and i.kind != BLANK]
        pages_md = markdown.text_pages_markdown(src, text_pages)
        for info in infos:
            if info.kind == BLANK:
                pages_md[info.page] = ""
            elif info.full_ocr:
                pages_md[info.page] = markdown.ocr_markdown(results[info.page][0])
            elif info.kind == MIXED:
                extra = [markdown.ocr_markdown(r) for r in results[info.page]]
                pages_md[info.page] = "\n\n".join([pages_md.get(info.page, "")] + [e for e in extra if e])
        pages_md, running_lines = markdown.strip_running_lines(pages_md)
        pages_md, merged_tables = markdown.merge_cross_page_tables(pages_md)
        with open(os.path.join(job_dir, OUTPUT_FILES["markdown"]), "w", encoding="utf-8") as f:
            f.write(markdown.build(pages_md))
        timings["markdown"] = time.perf_counter() - t

    if "pdf" in outputs:
        progress(i18n.t("stage.pdf", lang))
        t = time.perf_counter()
        searchable_pdf.build(src, infos, results, os.path.join(job_dir, OUTPUT_FILES["pdf"]))
        timings["pdf"] = time.perf_counter() - t

    if "docx" in outputs:
        t = time.perf_counter()
        word_merged = word.build(
            src_path, src, infos, results, job_dir, os.path.join(job_dir, OUTPUT_FILES["docx"]),
            images=options.get("word_images", "replace"),
            progress=lambda done, total: progress(i18n.t("stage.docx", lang), done, total),
            tables=options.get("word_tables", "keep"),
        )
        timings["docx"] = time.perf_counter() - t

    timings["total"] = time.perf_counter() - t0
    pages = []
    for info in infos:
        data = info.to_dict()
        data["ocr"] = info.page in results
        data["seconds"] = round(page_seconds[info.page], 1) if info.page in page_seconds else None
        if info.page in results:
            data["ocr_lines"] = sum(len(r.lines) for r in results[info.page])
            data["ocr_angle"] = results[info.page][0].angle
            if skew := results[info.page][0].skew:
                data["ocr_skew"] = skew  # 倾斜校正的角度
        pages.append(data)
    kinds: dict[str, int] = {}
    for info in infos:
        kinds[info.label] = kinds.get(info.label, 0) + 1
    summary = {"ocr_pages": len(results), "kinds": kinds}
    if deskewed := sum(1 for page in pages if page.get("ocr_skew")):
        summary["deskewed_pages"] = deskewed
    if options.get("source_type"):
        summary["converted_from"] = options["source_type"]
    if "markdown" in outputs:
        summary["cross_page_tables"] = merged_tables
        if running_lines:
            summary["running_lines"] = running_lines  # 去掉的页眉页脚
    if "docx" in outputs and options.get("word_tables") == "merge":
        summary["word_merged_tables"] = word_merged
    return {
        "page_count": len(infos),
        "summary": summary,
        "pages": pages,
        "files": [k for k in outputs if os.path.exists(os.path.join(job_dir, OUTPUT_FILES[k]))],
        "timings": {k: round(v, 1) for k, v in timings.items()},
    }
