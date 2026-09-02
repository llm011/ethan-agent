#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

_SKIP_KEYS = {"_source_file", "uncertain"}


def load_fields_yaml(fields_path):
    with fields_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    items = [
        (field["name"], category["category"], field.get("required", False))
        for category in data.get("field_categories", [])
        for field in category.get("fields", [])
    ]
    all_fields = {name for name, _, _ in items}
    required_fields = {name for name, _, required in items if required}
    field_categories = {name: category for name, category, _ in items}
    return all_fields, required_fields, field_categories


def extract_json_fields(data, category_names=None, known_fields=None):
    """递归提取 JSON 里的字段名。

    - 分类层判断不靠硬编码别名：category_names 来自 fields.yaml 的分类名集合。
    - 通用兜底：值为 dict 且 key 不是 fields.yaml 里定义的字段时，视为分组层下钻，
      兼容模型输出英文别名分组（如 basic_info）或自定义嵌套。
    - key 是已定义字段（即使值是 dict，如 pricing={...}）或值为非 dict 时，一律计为字段，
      避免字段名与分类别名撞车时被吞。
    """
    nested_keys = set(category_names or ())
    known = set(known_fields or ())
    fields = set()
    stack = [data]
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in _SKIP_KEYS:
                    continue
                if isinstance(v, dict) and (k in nested_keys or k not in known):
                    stack.append(v)
                    continue
                fields.add(k)
        elif isinstance(obj, list):
            stack.extend(item for item in obj if isinstance(item, (dict, list)))
    return fields


def validate_json(json_path, all_fields, required_fields, field_categories):
    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)
    json_fields = extract_json_fields(
        data,
        category_names=set(field_categories.values()),
        known_fields=all_fields,
    )
    covered = all_fields & json_fields
    missing = all_fields - json_fields
    extra = json_fields - all_fields
    missing_required = missing & required_fields
    missing_by_category = defaultdict(list)
    for field in missing:
        missing_by_category[field_categories.get(field, "未知")].append(field)
    return {
        "file": json_path.name,
        "total_defined": len(all_fields),
        "covered": len(covered),
        "missing": len(missing),
        "extra": len(extra),
        "coverage_rate": len(covered) / len(all_fields) * 100 if all_fields else 100,
        "missing_required": sorted(missing_required),
        "missing_optional": sorted(missing - required_fields),
        "missing_by_category": {k: sorted(v) for k, v in missing_by_category.items()},
        "extra_fields": sorted(extra),
        "valid": len(missing_required) == 0,
    }


def print_result(result, verbose=True):
    status = "通过" if result["valid"] else "失败"
    line = "=" * 60
    print(f"\n{line}")
    print(f"[{status}] {result['file']}")
    print(line)
    print(f"覆盖率: {result['coverage_rate']:.1f}% ({result['covered']}/{result['total_defined']})")
    if result["missing_required"]:
        print(f"\n[错误] 缺少必填字段 ({len(result['missing_required'])}):")
        print("\n".join(f"  - {f}" for f in result["missing_required"]))
    if verbose and result["missing_optional"]:
        missing_required = set(result["missing_required"])
        print(f"\n[警告] 缺少可选字段 ({len(result['missing_optional'])}):")
        for cat in sorted(result["missing_by_category"]):
            optional = [f for f in result["missing_by_category"][cat] if f not in missing_required]
            if optional:
                print(f"  [{cat}]: {', '.join(optional)}")
    if verbose and result["extra_fields"]:
        extra = result["extra_fields"]
        print(f"\n[信息] 额外字段 ({len(extra)}):")
        print(f"  {', '.join(extra[:10])}")
        if len(extra) > 10:
            print(f"  ... 还有 {len(extra) - 10} 个")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="验证JSON文件是否覆盖fields.yaml中定义的所有字段")
    parser.add_argument("--fields", "-f", type=str, help="fields.yaml路径", default="fields.yaml")
    parser.add_argument("--json", "-j", type=str, nargs="*", help="要验证的JSON文件路径")
    parser.add_argument("--dir", "-d", type=str, help="包含JSON文件的目录", default="results")
    parser.add_argument("--quiet", "-q", action="store_true", help="仅显示摘要")
    args = parser.parse_args()
    fields_path = Path(args.fields)
    if not fields_path.exists():
        for p in (Path.cwd() / "fields.yaml", Path.cwd().parent / "fields.yaml"):
            if p.exists():
                fields_path = p
                break
    if not fields_path.exists():
        print(f"[错误] 找不到fields.yaml: {fields_path}")
        sys.exit(1)
    print(f"字段定义文件: {fields_path}")
    all_fields, required_fields, field_categories = load_fields_yaml(fields_path)
    print(f"总字段数: {len(all_fields)} (必填: {len(required_fields)}, 可选: {len(all_fields) - len(required_fields)})")
    json_files = (
        [Path(p) for p in args.json]
        if args.json
        else sorted(Path(args.dir).glob("*.json")) if Path(args.dir).exists() else []
    )
    if not json_files:
        print("[警告] 未找到JSON文件")
        sys.exit(0)
    results = []
    for json_path in json_files:
        if not json_path.exists():
            print(f"[警告] 文件不存在: {json_path}")
            continue
        result = validate_json(json_path, all_fields, required_fields, field_categories)
        results.append(result)
        print_result(result, verbose=not args.quiet)
    line = "=" * 60
    print(f"\n{line}")
    print("汇总")
    print(line)
    passed = sum(1 for r in results if r["valid"])
    avg_coverage = sum(r["coverage_rate"] for r in results) / len(results) if results else 0
    print(f"验证通过: {passed}/{len(results)}")
    print(f"平均覆盖率: {avg_coverage:.1f}%")
    if passed < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
