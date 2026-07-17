"""迁移 facts.json → memory.db memories 表（新旧记忆系统融合）。

对所有 profile 执行。幂等：重跑跳过已迁移条目，不产生重复记忆。

用法：
    uv run python scripts/migrate_facts_to_memories.py            # 执行迁移
    uv run python scripts/migrate_facts_to_memories.py --dry-run  # 只统计不写库
"""
import argparse
import sys
from pathlib import Path

# 让脚本能 import ethan 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 facts.json 到结构化 memories 表")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库不归档")
    args = parser.parse_args()

    from ethan.memory.legacy_migration import migrate_all_users

    results = migrate_all_users(dry_run=args.dry_run)
    total = 0
    for uid, stats in results.items():
        if stats.get("error"):
            print(f"[FAIL] user={uid}")
            continue
        migrated = stats.get("migrated", 0)
        total += migrated
        if migrated or stats.get("skipped_existing") or stats.get("archived"):
            print(
                f"[{'DRY ' if args.dry_run else 'OK'}] user={uid} "
                f"migrated={migrated} skipped_existing={stats.get('skipped_existing', 0)} "
                f"skipped_superseded={stats.get('skipped_superseded', 0)} "
                f"archived={stats.get('archived', False)}"
            )
    print(f"\n[DONE] 共迁移 {total} 条" + ("（dry-run，未写库）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
