"""插件的中英文文案。语言来自凭据里的「语言」（language），没填时用英文。

同一个语言也决定发给服务端的 Accept-Language（服务端报错跟着变）和知识库分段开头的页码标注。
"""

from typing import Any

LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"

# key → (英文, 中文)
MESSAGES = {
    "bad_base_url": ("Service URL must start with http:// or https://", "服务地址需要以 http:// 或 https:// 开头"),
    "missing_api_key": ("API key is missing", "缺少 API Key"),
    "invalid_api_key": ("Invalid API key", "API Key 无效"),
    "timeout": ("Request to the PageSeam service timed out: {error}", "请求文档解析服务超时：{error}"),
    "unreachable": ("Cannot reach the PageSeam service at {url}: {error}", "无法连接文档解析服务 {url}：{error}"),
    "http_error": ("PageSeam service returned {status}: {detail}", "文档解析服务返回 {status}：{detail}"),
    "queue_full": ("The PageSeam service queue is full, please try again later", "文档解析服务排队已满，请稍后重试"),
    "job_failed": ("Parsing failed: {error}", "解析失败：{error}"),
    "missing_file": ("No file provided", "缺少文件"),
    "missing_job_id": ("job_id is missing", "缺少 job_id"),
    "no_extension": ("no extension", "无扩展名"),
    "unsupported_file": ("Unsupported file type: {extension}. Supported: {supported}", "不支持 {extension} 文件，支持：{supported}"),
    "still_running": (
        'The document is still being processed ({status}{detail}). Use the "Get Job Result" tool later with job_id={job_id} to fetch the result.',
        "文档仍在处理中（{status}{detail}）。请稍后用「查询任务结果」工具，传入 job_id={job_id} 获取结果。",
    ),
    "progress": (", {stage} {done}/{total}", "，{stage} {done}/{total}"),
    "converted": (
        "Converted {pages} pages, {ocr_pages} of them with OCR, in {seconds:.0f} s.",
        "已转换 {pages} 页，其中 {ocr_pages} 页做了 OCR，用时 {seconds:.0f} 秒。",
    ),
}

ACCEPT_LANGUAGE = {"en": "en", "zh": "zh-CN"}


def language(credentials: dict[str, Any] | None) -> str:
    value = str((credentials or {}).get("language") or "").strip().lower()
    return "zh" if value.startswith("zh") else DEFAULT_LANGUAGE


def t(key: str, lang: str = DEFAULT_LANGUAGE, **params: Any) -> str:
    en, zh = MESSAGES[key]
    return (zh if lang == "zh" else en).format(**params)


def page_label(pages: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """分段开头的页码：中文「第 3–5 页」，英文 "p. 3" / "pp. 3–5"。"""
    if lang == "zh":
        return f"第 {pages} 页"
    return f"pp. {pages}" if "–" in pages else f"p. {pages}"
