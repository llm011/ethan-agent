---
name: upload-cdn
version: 1.0.0
trigger: "上传CDN|上传图床|upload cdn|上传到CDN|上传文件到云|获取外链|公开链接|图片外链"
description: "上传本地文件到 S3 兼容对象存储（Cloudflare R2 等），返回公开访问 URL。当用户要上传图片/文件到 CDN、获取外链时使用。"
---

# upload-cdn

上传本地文件到 S3 兼容对象存储，返回公开 URL。支持 Cloudflare R2 及任意 S3 兼容服务。

## 密钥配置

凭证存放在 `~/.ethan/.secrets/upload-cdn.env`，由 shell 工具自动注入，**不要在对话中回显明文值**。

**第 0 步：先用 `list_secrets` 检查凭证是否已存。**
- 若输出包含 `upload-cdn.env` → 已配置，直接跳到「使用方法」。
- 若没有 → **立即停止**，不要再 find / read config 探索——凭证就是没有。直接告知用户需要提供以下字段（不要绕圈子）：

**第 1 步（凭证不存在时）：检测 shell 注入是否生效（可选快速确认）：**

```bash
test -n "$CDN_ENDPOINT" && test -n "$CDN_ACCESS_KEY" && test -n "$CDN_SECRET_KEY" \
  && test -n "$CDN_BUCKET" && test -n "$CDN_PUBLIC_URL" && echo READY || echo MISSING
```

- `READY` → 继续。
- `MISSING` → 凭证缺失。**直接**向用户索要以下字段，不要再探索其他路径：

| 字段 | 说明 | 示例 |
|------|------|------|
| `CDN_ENDPOINT` | S3 endpoint URL | `https://<account_id>.r2.cloudflarestorage.com` |
| `CDN_ACCESS_KEY` | Access Key ID | R2 → 管理 API 令牌 → 创建令牌 |
| `CDN_SECRET_KEY` | Secret Access Key | 同上 |
| `CDN_BUCKET` | 存储桶名 | `my-assets` |
| `CDN_PUBLIC_URL` | 公开访问 URL 前缀 | `https://cdn.example.com` 或 R2 公开域名 |
| `CDN_REGION` | 区域（可选） | R2 填 `auto`，其他填对应 region（默认 `auto`） |

拿到后**由 agent 写入**（`file_write` 工具，path=`~/.ethan/.secrets/upload-cdn.env`）：

```
CDN_ENDPOINT="https://<account_id>.r2.cloudflarestorage.com"
CDN_ACCESS_KEY="<access_key_id>"
CDN_SECRET_KEY="<secret_access_key>"
CDN_BUCKET="<bucket_name>"
CDN_PUBLIC_URL="https://cdn.example.com"
CDN_REGION="auto"
```

写完执行 `chmod 600 ~/.ethan/.secrets/upload-cdn.env`，然后**重新执行原始请求**。

## 使用方法

**单文件上传（指定 object key）：**
```bash
python ~/.ethan/skills/upload-cdn/scripts/upload_cdn.py /path/to/image.png images/image.png
```

**单文件上传（自动 key = 文件名）：**
```bash
python ~/.ethan/skills/upload-cdn/scripts/upload_cdn.py /path/to/report.pdf
```

**批量上传（shell 循环）：**
```bash
for f in /tmp/imgs/*.png; do
  python ~/.ethan/skills/upload-cdn/scripts/upload_cdn.py "$f" "docs/$(basename "$f")"
done
```

成功时 stdout 输出公开 URL，失败时 stderr 输出错误并 exit 非0。

## 注意事项

- Object key 建议带路径前缀（如 `docs/2024/image.png`），避免与其他文件冲突
- 同名 key 会覆盖已有文件
- 脚本纯标准库实现，无需额外依赖
