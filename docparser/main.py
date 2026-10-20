"""文档解析服务：PDF、Word（doc / docx）、图片 → Markdown（给知识库）/ 可搜索 PDF / Word。

逐页自动判断要不要 OCR：文字型页直接用原文，扫描页、乱码页和页内图片用 PaddleOCR 识别。
所有接口（除 /health 和上传页面）都需要 `Authorization: Bearer <API Key>`。
报错信息和逐页判定报告按请求的 `Accept-Language` 返回中文（zh）或英文（en），默认见 DEFAULT_LANGUAGE。
"""

import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import pymupdf
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from docparser import classify, config
from docparser.i18n import negotiate, t
from docparser.convert import IMAGE_TYPES, OFFICE_TYPES, image_to_pdf, looks_valid
from docparser.jobs import RUNNING, SUCCEEDED, JobManager, QueueFull

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

OUTPUTS = {
    "markdown": ("result.md", "text/markdown; charset=utf-8"),
    "pdf": ("result.pdf", "application/pdf"),
    "docx": ("result.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
}

manager: JobManager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global manager
    manager = JobManager()
    yield
    manager.shutdown()


app = FastAPI(
    title="PageSeam",
    version=config.VERSION,
    description=__doc__,
    lifespan=lifespan,
)
bearer = HTTPBearer(auto_error=False)


def language(request: Request) -> str:
    return negotiate(request.headers.get("accept-language"))


Lang = Annotated[str, Depends(language)]


def require_key(lang: Lang, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if not config.API_KEYS:
        raise HTTPException(503, t("no_api_keys", lang))
    if creds:
        for key in config.API_KEYS:
            if hmac.compare_digest(creds.credentials.encode(), key.encode()):
                return config.key_owner(key)
    raise HTTPException(401, t("invalid_key", lang), headers={"WWW-Authenticate": "Bearer"})


Owner = Annotated[str, Depends(require_key)]


class JobView(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    filename: str
    options: dict
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    progress: dict = {}
    page_count: int | None = None
    summary: dict = {}
    pages: list[dict] = []
    files: dict[str, str] = {}
    timings: dict = {}
    error: str | None = None


def _view(job, request: Request) -> JobView:
    result = job.result or {}
    base = str(request.base_url).rstrip("/")
    return JobView(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        options=job.options,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        progress=job.progress() if job.status == RUNNING else {},
        page_count=result.get("page_count"),
        summary=result.get("summary", {}),
        pages=result.get("pages", []),
        files={k: f"{base}/v1/jobs/{job.id}/files/{k}" for k in result.get("files", [])},
        timings=result.get("timings", {}),
        error=job.error,
    )


def _to_pdf(filename: str, data: bytes) -> bytes:
    """图片按单页 PDF 处理（整页 OCR）。"""
    ext = os.path.splitext(filename)[1].lower()
    return image_to_pdf(data) if ext in IMAGE_TYPES else data


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/v1/info", summary="服务信息和当前负载（可用于校验 API Key）")
def info(_owner: Owner):
    return {
        "version": config.VERSION,
        "outputs": list(OUTPUTS),
        "limits": {
            "max_file_mb": config.MAX_FILE_MB,
            "max_pages": config.MAX_PAGES,
            "max_workers": config.MAX_WORKERS,
            "max_queue": config.MAX_QUEUE,
            "job_ttl_minutes": config.JOB_TTL_MINUTES,
        },
        "jobs": manager.stats(),
    }


@app.post("/v1/jobs", status_code=202, response_model=JobView, summary="提交解析 / 转换任务")
async def create_job(
    request: Request,
    owner: Owner,
    lang: Lang,
    file: Annotated[UploadFile, File(description="PDF、Word（doc、docx）、PPT 或图片（png、jpg、tif 等）")],
    outputs: Annotated[str, Form(description="逗号分隔：markdown、pdf（可搜索 PDF）、docx")] = "markdown",
    ocr: Annotated[Literal["auto", "force", "off"], Form(description="auto 逐页自动判断；force 全部 OCR；off 不做 OCR")] = "auto",
    ocr_pages: Annotated[str, Form(description="额外指定整页 OCR 的页码，如 3,5-8")] = "",
    pages: Annotated[str, Form(description="只处理这些页，如 1-10；留空处理全部")] = "",
    word_images: Annotated[
        Literal["replace", "keep", "both"],
        Form(description="Word 中混合页的图片：replace 有文字的图片换成可编辑内容；keep 保留图片；both 保留图片并在下方附上识别内容"),
    ] = "replace",
    word_tables: Annotated[
        Literal["keep", "merge"],
        Form(description="Word 中的跨页表格：keep 和原件分页一致，每页一张表；merge 合并成一张表，表头跨页重复"),
    ] = "keep",
):
    wanted = [o.strip() for o in outputs.split(",") if o.strip()]
    unknown = set(wanted) - set(OUTPUTS)
    if not wanted or unknown:
        raise HTTPException(400, t("bad_outputs", lang, allowed=", ".join(OUTPUTS)))

    data = await file.read(config.MAX_FILE_MB * 1024 * 1024 + 1)
    if len(data) > config.MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, t("file_too_large", lang, mb=config.MAX_FILE_MB))
    filename = os.path.basename(file.filename or "document.pdf")
    ext = os.path.splitext(filename)[1].lower()
    if ext in OFFICE_TYPES:
        if not looks_valid(ext, data):
            raise HTTPException(400, t("invalid_office", lang, ext=ext.lstrip(".")))
        # Office 文档在工作进程中转成 PDF（可能要几十秒），转换后才知道页数，页码范围到时再校验
        options = {"outputs": wanted, "ocr": ocr, "pages_spec": pages, "ocr_pages_spec": ocr_pages,
                   "word_images": word_images, "word_tables": word_tables, "source_type": ext.lstrip("."), "lang": lang}
        return _submit(request, owner, lang, filename, data, options, "input" + ext)
    try:
        data = _to_pdf(filename, data)
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise HTTPException(400, t("pdf_password", lang))
            page_count = doc.page_count
            selected = classify.parse_page_ranges(pages, page_count) or set(range(1, page_count + 1))
            forced = classify.parse_page_ranges(ocr_pages, page_count)
    except HTTPException:
        raise
    except classify.PageRangeError as e:
        raise HTTPException(400, t("bad_page_range", lang, part=e.part)) from e
    except Exception as e:  # noqa: BLE001 — PyMuPDF 对损坏文件抛出的异常类型不固定
        raise HTTPException(400, t("unreadable", lang, error=e)) from e
    if len(selected) > config.MAX_PAGES:
        raise HTTPException(413, t("too_many_pages", lang, pages=len(selected), limit=config.MAX_PAGES))

    options = {
        "outputs": wanted,
        "ocr": ocr,
        "ocr_pages": sorted(forced),
        "pages": sorted(selected),
        "word_images": word_images,
        "word_tables": word_tables,
        "lang": lang,
    }
    return _submit(request, owner, lang, filename, data, options, "input.pdf")


def _submit(request: Request, owner: str, lang: str, filename: str, data: bytes, options: dict, input_name: str) -> JobView:
    try:
        job = manager.submit(owner, filename, data, options, input_name)
    except QueueFull:
        raise HTTPException(429, t("queue_full", lang), headers={"Retry-After": "30"}) from None
    return _view(job, request)


@app.get("/v1/jobs/{job_id}", response_model=JobView, summary="查询任务状态和结果")
def get_job(job_id: str, request: Request, owner: Owner, lang: Lang):
    job = manager.get(job_id, owner)
    if not job:
        raise HTTPException(404, t("job_not_found", lang))
    return _view(job, request)


@app.get("/v1/jobs/{job_id}/files/{kind}", summary="下载结果文件")
def download(job_id: str, kind: Literal["markdown", "pdf", "docx"], owner: Owner, lang: Lang):
    job = manager.get(job_id, owner)
    if not job or job.status != SUCCEEDED or kind not in job.result.get("files", []):
        raise HTTPException(404, t("file_not_found", lang))
    name, media_type = OUTPUTS[kind]
    stem = os.path.splitext(job.filename)[0]
    suffix = {"markdown": ".md", "pdf": "_ocr.pdf", "docx": ".docx"}[kind]
    return FileResponse(os.path.join(job.dir, name), media_type=media_type, filename=stem + suffix)


@app.delete("/v1/jobs/{job_id}", status_code=204, summary="删除任务和结果文件（处理中的任务不能删除）")
def delete_job(job_id: str, owner: Owner, lang: Lang):
    if not manager.delete(job_id, owner):
        raise HTTPException(404, t("job_not_deletable", lang))


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    with open(os.path.join(os.path.dirname(__file__), "static", "index.html"), encoding="utf-8") as f:
        return f.read().replace("{{VERSION}}", config.VERSION).replace("{{TTL}}", str(config.JOB_TTL_MINUTES))


@app.middleware("http")
async def timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path not in ("/health",):
        logging.getLogger("access").info(
            "%s %s %s %.0fms", request.method, request.url.path, response.status_code,
            (time.perf_counter() - start) * 1000,
        )
    return response
