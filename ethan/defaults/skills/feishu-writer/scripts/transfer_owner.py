#!/usr/bin/env python3
"""Transfer ownership of a Feishu Docx to another member.

Tries the v1 transfer_owner endpoint first; falls back to v2 on failure.

Credentials are read from ~/.ethan/.secrets/my_feishu.json — never hardcoded.

Usage:
    python transfer_owner.py <doc_token> --member-id <ou_xxx> [--member-type openid]
"""
import argparse
import json
import sys
from pathlib import Path

import requests

SECRETS_PATH = Path.home() / ".ethan" / ".secrets" / "my_feishu.json"
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
V1_URL = "https://open.feishu.cn/open-apis/drive/v1/permissions/{doc}/members/transfer_owner?type=docx"
V2_URL = "https://open.feishu.cn/open-apis/drive/v2/permissions/{doc}/members/transfer_owner?type=docx"


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


def main():
    parser = argparse.ArgumentParser(description="Transfer ownership of a Feishu Docx")
    parser.add_argument("doc_token", help="target docx token")
    parser.add_argument("--member-id", required=True, help="recipient id (openid / userid / departmentid)")
    parser.add_argument(
        "--member-type",
        default="openid",
        choices=["openid", "userid", "departmentid"],
        help="member type (default: openid)",
    )
    args = parser.parse_args()

    app_id, app_secret = load_credentials()
    token = get_tenant_token(app_id, app_secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"member_type": args.member_type, "member_id": args.member_id}

    v1_res = requests.post(
        V1_URL.format(doc=args.doc_token), headers=headers, json=payload, timeout=10
    ).json()
    print("v1 transfer_owner:", json.dumps(v1_res, ensure_ascii=False))
    if v1_res.get("code") == 0:
        return

    v2_res = requests.post(
        V2_URL.format(doc=args.doc_token), headers=headers, json=payload, timeout=10
    ).json()
    print("v2 transfer_owner:", json.dumps(v2_res, ensure_ascii=False))
    if v2_res.get("code") != 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
