#!/usr/bin/env python3
"""Inject a native Mermaid add_ons block (block_type=40) into a Feishu Docx.

Credentials are read from ~/.ethan/.secrets/my_feishu.json — never hardcoded.

Usage:
    python add_mermaid.py <doc_token> [--index N] [--mermaid 'graph TD...'] < mermaid.txt
"""
import argparse
import json
import sys
from pathlib import Path

import requests

SECRETS_PATH = Path.home() / ".ethan" / ".secrets" / "my_feishu.json"
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
CHILDREN_URL = "https://open.feishu.cn/open-apis/docx/v1/documents/{doc}/blocks/{doc}/children"
ADD_ONS_COMPONENT_TYPE_ID = "blk_631fefbbae02400430b8f9f4"


def load_credentials():
    if not SECRETS_PATH.exists():
        sys.stderr.write(
            f"[feishu-writer] secrets file missing: {SECRETS_PATH}\n"
            f"  Expected JSON format: {{\"app_id\":\"cli_xxx\",\"app_secret\":\"xxx\"}}\n"
        )
        sys.exit(2)
    try:
        data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[feishu-writer] invalid JSON in {SECRETS_PATH}: {exc}\n")
        sys.exit(2)
    app_id = data.get("app_id")
    app_secret = data.get("app_secret")
    if not app_id or not app_secret:
        sys.stderr.write(
            f"[feishu-writer] {SECRETS_PATH} missing app_id/app_secret fields\n"
        )
        sys.exit(2)
    return app_id, app_secret


def get_tenant_token(app_id, app_secret):
    res = requests.post(
        TOKEN_URL, json={"app_id": app_id, "app_secret": app_secret}, timeout=10
    ).json()
    token = res.get("tenant_access_token")
    if not token:
        sys.stderr.write(
            "[feishu-writer] failed to obtain tenant_access_token "
            f"(code={res.get('code')}, msg={res.get('msg')})\n"
        )
        sys.exit(3)
    return token


def read_mermaid(args):
    if args.mermaid:
        return args.mermaid
    if args.mermaid_file:
        return Path(args.mermaid_file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    sys.stderr.write(
        "[feishu-writer] no mermaid input: pass --mermaid, --mermaid-file, or pipe via stdin\n"
    )
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="Append a Mermaid add_ons block to a Feishu Docx")
    parser.add_argument("doc_token", help="target docx token")
    parser.add_argument("--index", type=int, default=-1, help="insertion index, -1 = append (default)")
    parser.add_argument("--mermaid", "-m", help="mermaid source string (use \\n for newlines)")
    parser.add_argument("--mermaid-file", help="path to a file containing mermaid source")
    args = parser.parse_args()

    mermaid_data = read_mermaid(args)

    app_id, app_secret = load_credentials()
    token = get_tenant_token(app_id, app_secret)

    block = {
        "block_type": 40,
        "add_ons": {
            "component_type_id": ADD_ONS_COMPONENT_TYPE_ID,
            "record": json.dumps(
                {"data": mermaid_data, "theme": "default", "view": "chart"},
                ensure_ascii=False,
            ),
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"children": [block], "index": args.index}
    url = CHILDREN_URL.format(doc=args.doc_token)
    res = requests.post(url, headers=headers, json=payload, timeout=15).json()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("code") != 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
