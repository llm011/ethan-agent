#!/usr/bin/env python3
"""一次性迁移：将 sessions.db 中的 base64 图片抽出到 ~/.ethan/assets/images/ 文件系统。

使用方法：
    python3 scripts/migrate_images_to_disk.py

迁移逻辑：
    1. 扫描 messages 表中 images 列不为空的记录
    2. 对每张含 "data" 字段的图片，写入文件并替换为 {path, media_type}
    3. 更新 DB 记录

幂等：已含 "path" 字段的图片不会重复处理。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# 确保能 import ethan 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ethan.core.assets import save_image  # noqa: E402
from ethan.core.paths import user_sessions_db_path  # noqa: E402


def migrate(db_path: Path | None = None) -> None:
    if db_path is None:
        db_path = user_sessions_db_path()

    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    cursor = conn.execute(
        "SELECT id, session_id, images FROM messages WHERE images IS NOT NULL AND images != '[]'"
    )
    rows = cursor.fetchall()
    print(f"Found {len(rows)} messages with images")

    updated = 0
    images_saved = 0

    for msg_id, session_id, images_json in rows:
        try:
            images = json.loads(images_json)
        except json.JSONDecodeError:
            continue

        if not images or not isinstance(images, list):
            continue

        changed = False
        new_images = []
        for idx, img in enumerate(images):
            if "path" in img:
                # 已迁移过
                new_images.append(img)
                continue
            data = img.get("data", "")
            media_type = img.get("media_type", "image/png")
            if not data:
                new_images.append(img)
                continue
            # 保存到文件
            path = save_image(session_id, idx, data, media_type)
            new_images.append({"path": path, "media_type": media_type})
            changed = True
            images_saved += 1

        if changed:
            conn.execute(
                "UPDATE messages SET images = ? WHERE id = ?",
                (json.dumps(new_images, ensure_ascii=False), msg_id),
            )
            updated += 1

    conn.commit()
    conn.close()
    print(f"Done: {updated} messages updated, {images_saved} images saved to disk")


if __name__ == "__main__":
    migrate()
