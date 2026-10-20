"""
把 WeKnora 空间的 MinerU 自建引擎地址指向 parser-bridge（也可以在 WeKnora 网页的解析引擎设置里手动填）。

这只是登记一个可选引擎：知识库在解析规则里把 pdf / docx 等选成 mineru 时才会用到 PageSeam，
其他知识库照常用内置解析器。已经是这个地址时不改动；其他解析引擎设置原样保留。输出一行：changed / unchanged。

环境变量：
  WEKNORA_BASE        WeKnora 后端地址，默认 http://127.0.0.1:8080
  WEKNORA_EMAIL       空间管理员账号
  WEKNORA_PASSWORD    密码
  PARSER_BRIDGE_ENDPOINT  默认 http://parser-bridge:8080（WeKnora 容器访问 parser-bridge 的地址）
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("WEKNORA_BASE", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
ENDPOINT = os.environ.get("PARSER_BRIDGE_ENDPOINT", "http://parser-bridge:8080")


def call(method: str, path: str, body=None, headers=None) -> dict:
    req = urllib.request.Request(
        BASE + path,
        json.dumps(body).encode() if body is not None else None,
        {"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        # 地址来自 WEKNORA_BASE 环境变量，不是用户输入
        return json.load(urllib.request.urlopen(req, timeout=30))  # nosec B310
    except urllib.error.HTTPError as e:
        raise SystemExit(f"❌ WeKnora {method} {path} 返回 {e.code}: {e.read().decode()[:200]}") from e


def main() -> int:
    try:
        email, password = os.environ["WEKNORA_EMAIL"], os.environ["WEKNORA_PASSWORD"]
    except KeyError:
        raise SystemExit("❌ 请设置 WEKNORA_EMAIL 和 WEKNORA_PASSWORD") from None
    login = call("POST", "/auth/login", {"email": email, "password": password})
    auth = {"Authorization": f"Bearer {login.get('token') or login['data']['token']}"}
    current = call("GET", "/tenants/kv/parser-engine-config", headers=auth).get("data") or {}
    wanted = {"mineru_endpoint": ENDPOINT, "mineru_parse_method": "auto"}
    if all(current.get(k) == v for k, v in wanted.items()):
        print("unchanged")
        return 0
    call("PUT", "/tenants/kv/parser-engine-config", {**current, **wanted}, auth)
    print("changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
