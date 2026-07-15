"""迁移 memory.db 的 vec_index 表到新维度（384 → 512）。

当 embeddings.py 的 EMBEDDING_DIM 改变后，旧 vec_index 表的 FLOAT[384] 不兼容新向量。
本脚本：
1. 备份 memory.db
2. 读取所有 vec_items (id, text)
3. 删除旧 vec_index 表
4. 用新 encoder 重新 embedding 所有 text
5. 创建新 vec_index 表（FLOAT[new_dim]）并写入

用法：
    uv run python scripts/migrate_memory_embeddings.py
    uv run python scripts/migrate_memory_embeddings.py --dry-run  # 只检查不迁移
"""
import argparse
import asyncio
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# 让脚本能 import ethan 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def get_current_dim(db_path: Path) -> int | None:
    """从 vec_index 表 schema 读出当前向量维度。表不存在/为空返回 None。"""
    conn = sqlite3.connect(str(db_path))
    try:
        import sqlite_vec as sv
        conn.enable_load_extension(True)
        sv.load(conn)
        conn.enable_load_extension(False)
        try:
            row = conn.execute("SELECT embedding FROM vec_index LIMIT 1").fetchone()
            if row is None:
                return None
            # float32 = 4 bytes per dim
            return len(row[0]) // 4
        except Exception:
            return None
    finally:
        conn.close()


async def migrate(db_path: Path, dry_run: bool = False, force: bool = False) -> None:
    import sqlite_vec as sv

    from ethan.memory.embeddings import EMBEDDING_DIM, embed

    print(f"目标维度: {EMBEDDING_DIM}")
    print(f"DB 路径: {db_path}")

    if not db_path.exists():
        print(f"[SKIP] DB 不存在: {db_path}")
        return

    current_dim = await get_current_dim(db_path)
    print(f"当前维度: {current_dim}")

    if current_dim is None:
        print("[SKIP] vec_index 表为空或不存在，无需迁移")
        return

    if current_dim == EMBEDDING_DIM and not force:
        print("[OK] 维度已匹配，无需迁移（--force 可强制重建）")
        return

    print(f"\n[NEED MIGRATE] {current_dim} → {EMBEDDING_DIM}")

    # 读出所有 vec_items
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sv.load(conn)
    conn.enable_load_extension(False)
    items = conn.execute("SELECT id, text FROM vec_items").fetchall()
    print(f"待迁移条目: {len(items)} 条")

    if dry_run:
        print("[DRY RUN] 不执行实际迁移")
        conn.close()
        return

    if not items:
        print("[SKIP] 没有条目需要迁移")
        conn.close()
        return

    # 备份
    backup = db_path.with_suffix(f".db.bak.{int(time.time())}")
    print(f"备份: {backup}")
    shutil.copy2(db_path, backup)

    # 用新 encoder 重新 embedding
    print("\n重新 embedding...")

    new_vecs: list[tuple[str, bytes]] = []
    t0 = time.time()
    for i, item in enumerate(items):
        emb = await embed(item["text"])
        emb_bytes = sv.serialize_float32(emb)
        new_vecs.append((item["id"], emb_bytes))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(items)} ({(i + 1) / len(items) * 100:.0f}%)")

    elapsed = time.time() - t0
    print(f"完成: {len(new_vecs)} 条, 耗时 {elapsed:.1f}s")

    # 重建 vec_index
    print("\n重建 vec_index 表...")
    conn.execute("DROP TABLE IF EXISTS vec_index")
    conn.execute(f"""
        CREATE VIRTUAL TABLE vec_index
        USING vec0(
            id      TEXT PRIMARY KEY,
            embedding FLOAT[{EMBEDDING_DIM}]
        )
    """)
    conn.executemany(
        "INSERT INTO vec_index (id, embedding) VALUES (?, ?)",
        new_vecs,
    )
    conn.commit()
    conn.close()

    print(f"\n[DONE] 迁移完成: {current_dim} → {EMBEDDING_DIM}, {len(new_vecs)} 条向量已重建")
    print(f"备份保留在: {backup}")


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 memory.db 的 embedding 维度")
    parser.add_argument("--dry-run", action="store_true", help="只检查不迁移")
    parser.add_argument("--force", action="store_true", help="强制重建 vec_index（即使维度已匹配）")
    parser.add_argument("--db", type=str, default=None, help="指定 db 路径（默认 ~/.ethan/memory/memory.db）")
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
    else:
        from ethan.core.paths import user_memory_dir
        db_path = user_memory_dir() / "memory.db"

    asyncio.run(migrate(db_path, dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    main()
