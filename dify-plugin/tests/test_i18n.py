"""插件文案：每条文案中英文参数一致、都能格式化；凭据里的语言怎么取值。

用法（在 dify-plugin 目录）: python3 -m unittest discover tests
"""

import os
import string
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.i18n import MESSAGES, language, page_label, t  # noqa: E402


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class I18nTest(unittest.TestCase):
    def test_messages_have_same_fields(self):
        for key, (en, zh) in MESSAGES.items():
            self.assertEqual(fields(en), fields(zh), key)
            params = {name: 1 for name in fields(en)}
            self.assertTrue(t(key, "en", **params) and t(key, "zh", **params), key)

    def test_language_from_credentials(self):
        self.assertEqual(language({}), "en")
        self.assertEqual(language(None), "en")
        self.assertEqual(language({"language": "zh"}), "zh")
        self.assertEqual(language({"language": "zh_Hans"}), "zh")
        self.assertEqual(language({"language": "fr"}), "en")

    def test_page_label(self):
        self.assertEqual(page_label("3"), "p. 3")
        self.assertEqual(page_label("3–5"), "pp. 3–5")
        self.assertEqual(page_label("3–5", "zh"), "第 3–5 页")


if __name__ == "__main__":
    unittest.main()
