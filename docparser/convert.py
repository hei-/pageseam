"""Office 文档转 PDF（LibreOffice），之后与 PDF 走同一条流程：逐页判断，扫描页和嵌入的扫描图片做 OCR。

为什么转成 PDF 而不是直接解析 docx：Word 里嵌入的扫描页、截图只有渲染出来才能 OCR；
原生文字转换后仍是 PDF 的文字层，逐页判断为文字型页，一个字都不改。
"""

import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from docparser import config
from docparser.i18n import t

# 扩展名 → LibreOffice 能打开的格式（文字处理、演示文稿）。表格类（xls/xlsx）转 PDF 会按打印区域分页，表格结构被打散，不支持
OFFICE_TYPES = {".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt", ".wps", ".ppt", ".pptx", ".odp", ".dps"}


# 文件头：新格式（docx、pptx、odt……）是 ZIP；旧格式（doc、ppt、wps……）是 OLE 复合文档。
# 不先检查的话，LibreOffice 会把任意文件当成纯文本打开，渲染出乱码页再去 OCR
_ZIP, _OLE, _RTF = b"PK\x03\x04", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"{\\rtf"
_SIGNATURES = {".rtf": (_RTF,), ".doc": (_OLE, _RTF), ".wps": (_OLE,), ".ppt": (_OLE,), ".dps": (_OLE,), ".dot": (_OLE,)}


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
# 图片识别时的最大边长（像素）：与 A4 扫描件按 200 DPI 渲染的大小相当
IMAGE_MAX_SIDE = 2400


class ConvertError(Exception):
    pass


def image_to_pdf(data: bytes) -> bytes:
    """图片转成 PDF，每张图一页（多页 TIFF 每帧一页），之后整页 OCR。

    - 页面大小按 OCR_DPI 换算，渲染时正好得到原图像素，不放大。pymupdf 默认按图片的 DPI 信息定页面大小，
      没有 DPI 信息时按 96，再按 200 DPI 渲染就放大了 2 倍多，表格模型在过大的图上会把行列认错（实测整张表错位）。
      超过 IMAGE_MAX_SIDE 的大图（如手机照片）按比例缩小。
    - 用 Pillow 读取：pymupdf 不支持 webp，也不处理手机照片的 EXIF 方向。
    """
    import io

    import pymupdf
    from PIL import Image, ImageOps, ImageSequence

    doc = pymupdf.open()
    with Image.open(io.BytesIO(data)) as img:
        for frame in ImageSequence.Iterator(img):
            frame = ImageOps.exif_transpose(frame)
            if frame.mode in ("RGBA", "LA", "P", "PA"):  # 透明背景按白色处理
                frame = frame.convert("RGBA")
                background = Image.new("RGB", frame.size, "white")
                background.paste(frame, mask=frame.split()[-1])
                frame = background
            elif frame.mode not in ("RGB", "L", "1"):
                frame = frame.convert("RGB")
            k = min(1.0, IMAGE_MAX_SIDE / max(frame.size))
            if k < 1:
                frame = frame.resize((round(frame.width * k), round(frame.height * k)), Image.LANCZOS)
            buf = io.BytesIO()
            if frame.mode == "RGB":
                frame.save(buf, "JPEG", quality=92)
            else:  # 黑白、灰度扫描件用 PNG，无损且体积小
                frame.save(buf, "PNG")
            page = doc.new_page(width=frame.width * 72 / config.OCR_DPI, height=frame.height * 72 / config.OCR_DPI)
            page.insert_image(page.rect, stream=buf.getvalue())
    return doc.tobytes()


def looks_valid(ext: str, data: bytes) -> bool:
    """文件内容和扩展名对应的格式是否一致（doc 允许是 RTF：很多「.doc」其实是另存的 RTF）。"""
    return data.startswith(_SIGNATURES.get(ext, (_ZIP,)))


WORD_ZIP_TYPES = {".docx", ".docm", ".dotx"}
_CJK_LANGS = ("zh", "ja", "ko")
_KANA, _HANGUL, _HAN = re.compile(r"[぀-ヿ]"), re.compile(r"[가-힣]"), re.compile(r"[一-鿿]")
_LANG_DEFAULT = re.compile(r"(<w:rPrDefault>.*?)(<w:lang\b[^>]*?)(/?>)(.*?</w:rPrDefault>)", re.S)


def fix_east_asian_language(data: dict[str, bytes]) -> bool:
    """docx 的默认东亚语言不是中日韩语言（如 python-docx、英文版 Word 模板里的 en-US），正文却是中文时，
    LibreOffice 把弯引号 “” 等中西文共用的标点当成西文，用西文字体渲染。字体不同、字形高度不同，
    PDF 文字层里引号成了单独的行，提取时被挪到句末（「关键词车型。“ ”」）。
    把默认东亚语言改成正文的语言，引号就和正文用同一种字体。data 是 {zip 内路径: 内容}，原地修改；返回是否改动。
    """
    body = data.get("word/document.xml", b"").decode("utf-8", "ignore")
    styles = data.get("word/styles.xml")
    if not styles or not _HAN.search(body) and not _HANGUL.search(body):
        return False
    lang = "ja-JP" if _KANA.search(body) else "ko-KR" if _HANGUL.search(body) and not _HAN.search(body) else "zh-CN"
    text = styles.decode("utf-8")
    m = _LANG_DEFAULT.search(text)
    if m:
        attrs = m.group(2)
        current = re.search(r'w:eastAsia="([^"]*)"', attrs)
        if current and current.group(1).lower().startswith(_CJK_LANGS):
            return False
        attrs = re.sub(r'w:eastAsia="[^"]*"', f'w:eastAsia="{lang}"', attrs) if current else f'{attrs} w:eastAsia="{lang}"'
        text = text[: m.start(2)] + attrs + text[m.end(2):]
    elif "<w:rPrDefault><w:rPr>" in text:
        text = text.replace("<w:rPrDefault><w:rPr>", f'<w:rPrDefault><w:rPr><w:lang w:eastAsia="{lang}"/>', 1)
    else:
        return False
    data["word/styles.xml"] = text.encode("utf-8")
    return True


def _prepare_source(src_path: str, work: str) -> str:
    """需要预处理时在 work 下写一份改过的副本（文件名不变，LibreOffice 按它命名输出），返回要转换的路径。"""
    if os.path.splitext(src_path)[1].lower() not in WORD_ZIP_TYPES:
        return src_path
    try:
        with zipfile.ZipFile(src_path) as zin:
            infos = zin.infolist()
            data = {i.filename: zin.read(i) for i in infos}
    except (zipfile.BadZipFile, OSError):
        return src_path
    if not fix_east_asian_language(data):
        return src_path
    dst = os.path.join(work, "src", os.path.basename(src_path))
    os.makedirs(os.path.dirname(dst))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in infos:
            zout.writestr(i, data[i.filename])
    return dst


def to_pdf(src_path: str, out_path: str, lang: str | None = None) -> None:
    """转换 src_path 为 PDF，写到 out_path。每次转换使用独立的 LibreOffice 配置目录，多个任务可以并行。"""
    work = tempfile.mkdtemp(prefix="lo-", dir=os.path.dirname(out_path))
    try:
        src_path = _prepare_source(src_path, work)
        cmd = [
            config.LIBREOFFICE, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
            f"-env:UserInstallation=file://{work}/profile",
            "--convert-to", "pdf", "--outdir", work, src_path,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=config.CONVERT_TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            raise ConvertError(t("convert_timeout", lang, seconds=config.CONVERT_TIMEOUT)) from None
        produced = os.path.join(work, os.path.splitext(os.path.basename(src_path))[0] + ".pdf")
        if proc.returncode != 0 or not os.path.exists(produced):
            detail = (proc.stderr or proc.stdout or "").strip()[-300:]
            raise ConvertError(t("convert_failed", lang, detail=detail))
        shutil.move(produced, out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
