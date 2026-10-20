"""中英文文案：Accept-Language 协商、每条文案两种语言都能格式化。

用法: python tests/test_i18n.py（只依赖标准库）
"""

import os
import string
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from docparser import config  # noqa: E402
from docparser.i18n import MESSAGES, negotiate, t  # noqa: E402

failed = 0


def check(ok: bool, name: str) -> None:
    global failed
    print(("✅ " if ok else "❌ ") + name)
    failed += not ok


check(negotiate("zh-CN,zh;q=0.9,en;q=0.8") == "zh", "浏览器中文优先 → zh")
check(negotiate("en-US,en;q=0.9,zh-CN;q=0.8") == "en", "浏览器英文优先 → en")
check(negotiate("fr-FR,zh;q=0.5,en;q=0.7") == "en", "不支持的语言跳过，按 q 值取 en")
check(negotiate("zh-TW") == "zh", "繁体中文也返回中文（只有简体文案）")
check(negotiate(None) == config.DEFAULT_LANGUAGE, "没有 Accept-Language → 默认语言")
check(negotiate("*") == config.DEFAULT_LANGUAGE, "通配符 → 默认语言")
check(negotiate("en;q=abc,zh") == "zh", "q 值写错的语言忽略")

sample = {"allowed": "a", "mb": 1, "ext": "doc", "error": "x", "pages": 2, "limit": 1, "part": "x", "seconds": 1,
          "detail": "x", "hidden": 1, "visible": 1, "coverage": 0.5, "drawings": 1, "ratio": 0.9, "font": "F",
          "regions": 1, "label": "L"}
for key, texts in MESSAGES.items():
    fields = [{f for _, f, _, _ in string.Formatter().parse(s) if f} for s in texts]
    check(fields[0] == fields[1], f"{key}：中英文参数一致")
    check(all(t(key, lang, **sample) for lang in ("en", "zh")), f"{key}：两种语言都能格式化")
check(t("invalid_key", "zh") == "API Key 无效" and t("invalid_key", "en") == "Invalid API key", "按语言取文案")

sys.exit(1 if failed else 0)
