"""接口报错、任务进度和逐页判定报告的中英文文案。

语言按请求的 Accept-Language 选择（zh* → 中文，en* → 英文，按 q 值取最优），没有或都不匹配时用 DEFAULT_LANGUAGE。
任务在提交时记下语言，工作进程生成的进度、判定和错误信息都用这个语言。
"""

from docparser import config

LANGUAGES = ("en", "zh")

# key: (English, 中文)
MESSAGES = {
    # 接口报错
    "no_api_keys": ("API_KEYS is not configured on the server", "服务未配置 API_KEYS"),
    "invalid_key": ("Invalid API key", "API Key 无效"),
    "bad_outputs": ("outputs must be one or more of: {allowed}", "outputs 只能是 {allowed}"),
    "file_too_large": ("File exceeds {mb} MB", "文件超过 {mb}MB"),
    "invalid_office": (
        "Not a valid {ext} file (it may be corrupted, or the extension is wrong)",
        "文件内容不是有效的 {ext} 文件（可能已损坏，或扩展名不对）",
    ),
    "pdf_password": ("The PDF is password-protected; remove the password first", "PDF 有打开密码，请先解除密码"),
    "unreadable": ("Cannot read the file: {error}", "无法读取文件：{error}"),
    "too_many_pages": ("{pages} pages exceed the limit of {limit}", "页数 {pages} 超过上限 {limit}"),
    "bad_page_range": ("Invalid page range: {part}", "页码范围无效：{part}"),
    "queue_full": ("The queue is full, please retry later", "排队任务已满，请稍后重试"),
    "job_not_found": ("Job not found or expired", "任务不存在或已过期"),
    "file_not_found": ("File not found", "文件不存在"),
    "job_not_deletable": ("Job not found, or still processing", "任务不存在，或仍在处理中"),
    "convert_timeout": ("Conversion to PDF timed out ({seconds} s)", "转换为 PDF 超时（{seconds} 秒）"),
    "convert_failed": (
        "Cannot convert to PDF (corrupted, password-protected or unsupported file): {detail}",
        "无法转换为 PDF（文件损坏、有密码保护或格式不支持）：{detail}",
    ),
    # 任务进度
    "stage.convert": ("Converting to PDF", "转换为 PDF"),
    "stage.classify": ("Classifying pages", "识别页面类型"),
    "stage.ocr": ("Running OCR", "OCR 识别"),
    "stage.markdown": ("Generating Markdown", "生成 Markdown"),
    "stage.pdf": ("Generating searchable PDF", "生成可搜索 PDF"),
    "stage.docx": ("Generating Word", "生成 Word"),
    # 页面判定（classify.py 的 kind）
    "kind.scan": ("Scanned page", "扫描页"),
    "kind.scan_old_ocr": ("Scanned page (old OCR layer replaced)", "扫描页（带旧 OCR 层，已重新识别）"),
    "kind.garbled": ("Garbled text", "乱码页"),
    "kind.outlined": ("Text as outlines", "文字已转曲线"),
    "kind.mixed": ("Mixed page", "混合页"),
    "kind.text": ("Text page", "文字型页"),
    "kind.blank": ("Blank page", "空白页"),
    "kind.forced": ("OCR requested", "指定 OCR"),
    # 判定依据
    "reason.scan_old_ocr": (
        "Full-page image with a hidden text layer of {hidden} characters",
        "整页是图片，带 {hidden} 字的隐藏文字层",
    ),
    "reason.scan": ("{visible} characters of text, images cover {coverage:.0%}", "文字 {visible} 字，图片覆盖 {coverage:.0%}"),
    "reason.outlined": ("No text, but {drawings} vector paths", "没有文字，但有 {drawings} 个矢量路径"),
    "reason.blank": ("No text or images", "没有文字和图片"),
    "reason.garbled": ("Only {ratio:.0%} valid characters", "有效字符仅 {ratio:.0%}"),
    "reason.no_unicode": (
        "Font {font} has no Unicode mapping; extracted text is unreliable",
        "字体 {font} 缺少编码映射，提取的文字不可靠",
    ),
    "reason.mixed": (
        "{visible} characters of text, {regions} images need OCR (images cover {coverage:.0%})",
        "文字 {visible} 字，{regions} 张图片需要 OCR（图片覆盖 {coverage:.0%}）",
    ),
    "reason.text": ("{visible} characters of text, {ratio:.0%} valid", "文字 {visible} 字，有效字符 {ratio:.0%}"),
    "reason.forced": ("Full-page OCR requested by user; ", "用户指定整页 OCR；"),
    "reason.off": ("OCR turned off (detected as {label}); ", "已关闭 OCR（自动判断为{label}）；"),
}


def t(key: str, lang: str | None = None, **params) -> str:
    en, zh = MESSAGES[key]
    return (zh if (lang or config.DEFAULT_LANGUAGE) == "zh" else en).format(**params)


def negotiate(accept_language: str | None) -> str:
    """从 Accept-Language 中选出 q 值最高的受支持语言，如 "zh-CN,zh;q=0.9,en;q=0.8" → zh。"""
    best, best_q = None, 0.0
    for part in (accept_language or "").split(","):
        tag, _, params = part.partition(";")
        q = 1.0
        params = params.strip().lower()
        if params.startswith("q="):
            try:
                q = float(params[2:])
            except ValueError:
                q = 0.0
        lang = tag.strip().lower().split("-")[0]
        if lang in LANGUAGES and q > best_q:
            best, best_q = lang, q
    return best or config.DEFAULT_LANGUAGE
