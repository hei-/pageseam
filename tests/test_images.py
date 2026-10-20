"""图片转 PDF 的单元测试（不需要 OCR 模型）。

用法（在服务镜像中执行）: python tests/test_images.py
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from docparser import config  # noqa: E402
from docparser.convert import IMAGE_MAX_SIDE, image_to_pdf  # noqa: E402


def encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def pages(data: bytes) -> list[tuple[int, int]]:
    """按 OCR_DPI 渲染后每页的像素尺寸。"""
    with pymupdf.open("pdf", image_to_pdf(data)) as doc:
        return [(p.get_pixmap(dpi=config.OCR_DPI).width, p.get_pixmap(dpi=config.OCR_DPI).height) for p in doc]


def test_native_resolution():
    """渲染后正好是原图像素，不放大；不管图片里的 DPI 信息是多少。"""
    img = Image.new("RGB", (1754, 1240), "white")
    for fmt, kwargs in [("JPEG", {}), ("JPEG", {"dpi": (72, 72)}), ("PNG", {"dpi": (300, 300)}), ("BMP", {}), ("WEBP", {})]:
        assert pages(encode(img, fmt, **kwargs)) == [(1754, 1240)], (fmt, kwargs)


def test_large_image_scaled_down():
    img = Image.new("RGB", (4000, 3000), "white")
    w, h = pages(encode(img, "JPEG"))[0]
    assert max(w, h) <= IMAGE_MAX_SIDE + 1 and abs(w / h - 4 / 3) < 0.01, (w, h)


def test_multipage_tiff():
    frames = [Image.new("L", (800, 1000), v) for v in (255, 200, 150)]
    buf = io.BytesIO()
    frames[0].save(buf, "TIFF", save_all=True, append_images=frames[1:])
    assert pages(buf.getvalue()) == [(800, 1000)] * 3


def test_exif_orientation():
    """手机竖拍的照片：像素是横的，EXIF 标记需要旋转 90°。"""
    img = Image.new("RGB", (1200, 900), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # 顺时针旋转 90° 显示
    assert pages(encode(img, "JPEG", exif=exif)) == [(900, 1200)]


def test_transparent_png_on_white():
    img = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    with pymupdf.open("pdf", image_to_pdf(encode(img, "PNG"))) as doc:
        pix = doc[0].get_pixmap(dpi=config.OCR_DPI)
        assert pix.pixel(10, 10)[:3] == (255, 255, 255)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
