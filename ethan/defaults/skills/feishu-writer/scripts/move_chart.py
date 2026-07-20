#!/usr/bin/env python3
"""Move a Mermaid add_ons block: delete an old block, then insert a fresh one
right after the block whose text contains --anchor-text.

Credentials are read from ~/.ethan/.secrets/my_feishu.json — never hardcoded.

Usage:
    python move_chart.py <doc_token> \\
        --delete-block-id <block_id> \\
        --anchor-text "unique snippet in target paragraph" \\
        --mermaid-file mermaid.txt
"""
import argparse
import json
import sys
from pathlib import Path

import requests

SECRETS_PATH = Path.home() / ".ethan" / ".secrets" / "my_feishu.json"
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
CHILDREN_URL = "https://open.feishu.cn/open-apis/docx/v1/documents/{doc}/blocks/{doc}/children"
BLOCK_URL = "https://open.feishu.cn/open-apis/docx/v1/documents/{doc}/blocks/{block}"
ADD_ONS_COMPONENT_TYPE_ID = "blk_631fefbbae02400430b8f9f4"


def load_credentials():
    if not SECRETS_PATH.exists():
        sys.stderr.write(
            f"[feishu-writer] secrets file missing: {SECRETS_PATH}\n"
            f"  Expected JSON format: {{\"app_id\":\"cli_xxx\",\"app_secret\":\"xxx\"}}\n"
        )
        sys.exit(2)
    data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
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
    if args.mermaid_file:
        return Path(args.mermaid_file).read_text(encoding="utf-8")
    if args.mermaid:
        return args.mermaid
    if not sys.stdin.isatty():
        return sys.stdin.read()
    sys.stderr.write(
        "[feishu-writer] no mermaid input: pass --mermaid, --mermaid-file, or pipe via stdin\n"
    )
    sys.exit(2)


def find_anchor_index(children, anchor_text):
    for i, block in enumerate(children):
        if block.get("block_type") != 2:
            continue
        elements = block.get("text", {}).get("elements", [])
        for el in elements:
            content = el.get("text_run", {}).get("content", "")
            if anchor_text in content:
                return i + 1
    return -1


def main():
    parser = argparse.ArgumentParser(
        description="Delete a block and insert a Mermaid add_ons block after an anchor paragraph"
    )
    parser.add_argument("doc_token", help="target docx token")
    parser.add_argument("--delete-block-id", required=True, help="block id to delete")
    parser.add_argument("--anchor-text", required=True, help="unique text snippet in the anchor paragraph")
    parser.add_argument("--mermaid", "-m", help="mermaid source string")
    parser.add_argument("--mermaid-file", help="path to a file containing mermaid source")
    args = parser.parse_args()

    mermaid_data = read_mermaid(args)

    app_id, app_secret = load_credentials()
    token = get_tenant_token(app_id, app_secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    # 1. Delete the old block
    del_url = BLOCK_URL.format(doc=args.doc_token, block=args.delete_block_id)
    del_res = requests.delete(del_url, headers=headers, timeout=10).json()
    print("delete:", json.dumps(del_res, ensure_ascii=False))
    if del_res.get("code") != 0:
        sys.stderr.write("[feishu-writer] delete failed; aborting before insert\n")
        sys.exit(1)

    # 2. List children to locate the anchor
    list_url = CHILDREN_URL.format(doc=args.doc_token)
    list_res = requests.get(list_url, headers=headers, timeout=10).json()
    if list_res.get("code") != 0:
        sys.stderr.write(
            f"[feishu-writer] list children failed: {list_res}\n"
        )
        sys.exit(1)
    children = list_res.get("data", {}).get("items", [])
    target_idx = find_anchor_index(children, args.anchor_text)
    print(f"target insert index: {target_idx}")
    if target_idx == -1:
        sys.stderr.write(
            f"[feishu-writer] anchor text not found in any text block: {args.anchor_text!r}\n"
        )
        sys.exit(1)

    # 3. Insert the new Mermaid block at target_idx
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
    payload = {"children": [block], "index": target_idx}
    create_res = requests.post(list_url, headers=headers, json=payload, timeout=15).json()
    print(json.dumps(create_res, ensure_ascii=False, indent=2))
    if create_res.get("code") != 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
