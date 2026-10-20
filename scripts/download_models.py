"""构建镜像时预下载 OCR 模型：按服务实际使用的配置加载引擎，并识别一张生成的图片。

部分模型（如页面方向分类）在第一次识别时才下载，所以必须真正跑一次识别。
"""

import sys
import time

sys.path.insert(0, "/app")

import pymupdf  # noqa: E402

from docparser import ocr  # noqa: E402

start = time.time()
doc = pymupdf.open()
page = doc.new_page()
page.insert_htmlbox(
    pymupdf.Rect(50, 50, 545, 400),
    "<h2>模型预下载</h2><p>文档解析服务构建镜像时识别这张图片。</p>"
    "<table border='1'><tr><td>项目</td><td>金额</td></tr><tr><td>测试</td><td>1,000.00</td></tr></table>",
)
result = ocr.recognize(page)
print(f"models ready in {time.time() - start:.0f}s: {[l.text for l in result.lines]}")
