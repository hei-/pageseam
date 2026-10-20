# Third-party notices

English | [简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

PageSeam itself is released under [AGPL-3.0](LICENSE). AGPL was chosen because the core dependencies PyMuPDF, pymupdf4llm and pymupdf-layout are dual-licensed under **AGPL-3.0 / Artifex commercial license**:

- When used under AGPL, **offering the service to others over a network (including SaaS) requires making the complete source, including your changes, available to those users**.
- If you don't want to release your source, buy a commercial license for the PyMuPDF family from [Artifex](https://artifex.com/licensing).

All other dependencies use permissive licenses (MIT, BSD, Apache-2.0, etc.) or weak copyleft (LGPL, MPL-2.0: no extra obligations when used unmodified as libraries).

This list is not legal advice. Verify it yourself before commercial use or redistribution.

## System components in the runtime image

| Component | Purpose | License |
|-----------|---------|---------|
| Debian (`python:3.11-slim` base image) | Operating system | Each package's own license |
| LibreOffice (writer-nogui, impress-nogui) | doc, docx, ppt etc. → PDF, run as a separate process | MPL-2.0 |
| Noto CJK fonts (`fonts-noto-cjk`) | Replacement for Chinese fonts | SIL OFL 1.1 |
| PaddleOCR models (PP-DocLayout-M, PP-OCRv5, SLANet_plus) | OCR, layout and table recognition, downloaded at build time | Apache-2.0 |

## Python dependencies (direct)

| Package | License |
|---------|---------|
| fastapi, python-docx, docxcompose, pdf2docx | MIT |
| uvicorn, starlette | BSD-3-Clause |
| python-multipart, paddlepaddle, paddleocr | Apache-2.0 |
| **pymupdf, pymupdf4llm (and its dependency pymupdf-layout)** | **AGPL-3.0 or Artifex commercial license** |

## Python dependencies (all packages in the image)

Read with `importlib.metadata` from the CPU image; versions change with build time.

| Package | Version | License |
|----|------|--------|
| aiohappyeyeballs | 2.7.1 | Python Software Foundation License |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache Software License |
| aistudio_sdk | 0.3.9 | Apache Software License |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| babel | 2.18.0 | BSD License |
| bce-python-sdk | 0.9.79 | Apache License 2.0 |
| beautifulsoup4 | 4.15.0 | MIT License |
| cachetools | 7.2.4 | MIT |
| certifi | 2026.10.19 | Mozilla Public License 2.0 (MPL 2.0) |
| cffi | 2.1.1 | MIT-0 |
| chardet | 7.7.0 | 0BSD |
| charset-normalizer | 3.5.2 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| cloudpickle | 3.1.2 | BSD License |
| colorlog | 6.12.0 | MIT License |
| crc32c | 2.9.post0 | GNU Lesser General Public License v2 or later (LGPLv2+) |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| cssselect | 1.6.0 | BSD-3-Clause |
| cssutils | 2.15.0 | LGPL-3.0-or-later |
| docxcompose | 2.2.0 | MIT License |
| einops | 0.8.2 | MIT License |
| encutils | 1.0.0 | LGPL-3.0-or-later |
| et_xmlfile | 2.0.0 | MIT License |
| fastapi | 0.142.2 | MIT |
| filelock | 4.2.4 | MIT |
| fire | 0.7.1 | Apache-2.0 |
| flatbuffers | 25.12.19 | Apache Software License |
| fonttools | 4.67.0 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| fsspec | 2026.9.0 | BSD-3-Clause |
| ftfy | 6.3.1 | Apache-2.0 |
| future | 1.0.0 | OSI Approved; MIT License |
| h11 | 0.16.0 | MIT License |
| hf-xet | 1.7.0 | Apache-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.15.1 | BSD-3-Clause |
| httptools | 0.9.0 | MIT |
| httpx | 0.28.1 | BSD License |
| httpx2 | 2.15.1 | BSD-3-Clause |
| huggingface_hub | 2.2.0 | Apache Software License |
| idna | 3.20 | BSD-3-Clause |
| imagesize | 2.0.1 | MIT |
| Jinja2 | 3.1.6 | BSD License |
| jiter | 0.17.0 | MIT |
| joblib | 1.6.0 | BSD-3-Clause |
| latex2mathml | 3.81.1 | MIT |
| lxml | 6.1.3 | BSD-3-Clause |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| modelscope | 1.40.2 | Apache-2.0 |
| modelscope-hub | 0.4.6 | Apache Software License |
| more-itertools | 11.2.1 | MIT |
| multidict | 7.1.0 | Apache-2.0 |
| narwhals | 2.27.1 | MIT |
| networkx | 3.6.1 | BSD-3-Clause |
| numpy | 2.3.5 | BSD License |
| onnxruntime | 1.31.0 | MIT License |
| openai | 3.35.1 | Apache-2.0 |
| opencv-contrib-python | 4.10.0.84 | Apache Software License |
| opencv-python-headless | 5.0.0.93 | Apache Software License |
| openpyxl | 3.1.5 | MIT License |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| opt-einsum | 3.3.0 | OSI Approved |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| paddleocr | 3.7.0 | Apache License 2.0 |
| paddlepaddle | 3.2.2 | Apache Software License |
| paddlex | 3.7.2 | Apache-2.0 |
| pandas | 3.0.6 | BSD License |
| pdf2docx | 0.5.13 | MIT |
| pillow | 13.0.0 | MIT-CMU |
| pip | 26.2.1 | MIT |
| premailer | 3.10.0 | Python Software Foundation License |
| prettytable | 3.18.0 | BSD-3-Clause |
| propcache | 0.5.4 | Apache-2.0 |
| protobuf | 7.36.2 | 3-Clause BSD License |
| psutil | 7.2.2 | BSD-3-Clause |
| py-cpuinfo | 9.0.0 | MIT License |
| pyclipper | 1.4.0 | OSI Approved; MIT License |
| pycparser | 3.11 | BSD-3-Clause |
| pycryptodome | 4.1.0 | BSD-2-Clause AND Unlicense AND MIT |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| pymupdf | 1.28.2 | AGPL-3.0 or Artifex commercial |
| pymupdf-layout | 1.28.2 | AGPL-3.0 or Artifex commercial (COPYING in the package) |
| pymupdf4llm | 1.28.2 | AGPL-3.0 or Artifex commercial |
| pypdfium2 | 5.14.0 | BSD-3-Clause, Apache-2.0, dependency licenses |
| python-bidi | 0.6.11 | GNU Library or Lesser General Public License (LGPL) |
| python-dateutil | 2.9.0.post0 | BSD License; Apache Software License |
| python-docx | 1.2.0 | MIT License |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| PyYAML | 6.0.2 | MIT License |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache Software License |
| ruamel.yaml | 0.19.1 | MIT License |
| safetensors | 0.8.0 | Apache Software License |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| scipy | 1.17.1 | BSD License |
| sentencepiece | 0.2.2 | Apache-2.0 |
| setuptools | 79.0.1 | UNKNOWN |
| shapely | 2.2.0 | BSD-3-Clause |
| six | 1.17.0 | MIT License |
| sniffio | 1.3.1 | MIT License; Apache Software License |
| soupsieve | 3.0.3 | MIT |
| starlette | 1.7.0 | BSD-3-Clause |
| tabulate | 0.10.0 | MIT |
| termcolor | 3.3.0 | MIT |
| threadpoolctl | 3.7.0 | BSD-3-Clause |
| tiktoken | 0.14.0 | MIT License |
| tokenizers | 0.23.3 | Apache Software License |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| truststore | 0.10.5 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| ujson | 6.0.0 | BSD-3-Clause AND TCL |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.34.2 | BSD-3-Clause |
| uvloop | 0.23.0 | Apache Software License; MIT License |
| watchfiles | 1.3.0 | MIT License |
| wcwidth | 0.9.2 | MIT License |
| websockets | 17.3 | BSD-3-Clause |
| wheel | 0.46.3 | MIT |
| yarl | 1.25.1 | Apache-2.0 |

## Dify plugin (`dify-plugin/`)

The plugin only calls the service over HTTP and does not contain PyMuPDF; it is released separately under [MIT](dify-plugin/LICENSE). Dependencies: `dify_plugin` (Apache-2.0), `httpx` (BSD-3-Clause).

## WeKnora bridge (`integrations/weknora/`)

Uses only the Python standard library and calls the service over HTTP; released separately under [MIT](integrations/weknora/LICENSE).
