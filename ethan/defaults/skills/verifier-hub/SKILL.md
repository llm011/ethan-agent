---
name: verifier-hub
description: 产物交付前的确定性校验 CLI。回答「文件在不在、空不空、有没有占位符、语法对不对」这类有确定答案的问题，替代"让模型读一遍再猜"。在把文件交给用户/上传前使用：md/txt/json/html/py/js/png/jpg 等产物先用 check 一键校验（存在 + 非空 + 占位符审计 + 语法/魔数），输出可引用的 JSON 证据。
trigger:
  - 交付前检查
  - 校验产物
  - 检查文件
  - 占位符
  - 空文件
  - verify
  - artifact check
---

# verifier-hub（简化版）：产物确定性校验

交付前自检工具。**校验不靠模型读一遍判断，靠脚本跑出确定性结论**，每次输出一个可引用的 JSON 证据对象。

脚本：`scripts/verify.py`（stdlib only，无第三方依赖）。

## 核心用法：`check` 一键全家桶

```bash
python3 <skill>/scripts/verify.py check <path> [--must-contain 关键词]...
```

按扩展名自动选检查类型，串行跑「文件级 + 内容级」两层：

| 扩展名 | 内容级检查 |
|---|---|
| `.md` `.txt` | 非空白 + 占位符审计 + 关键词 |
| `.json` | 可解析 + 键存在 |
| `.html` `.htm` | 可解析 + 正文非空（≥10 字符）+ 占位符 |
| `.py` | py_compile 语法编译 |
| `.js` `.mjs` | node --check（无 node 时降级报 DEP_MISSING） |
| 图片 | 非空 + 魔数（png/jpg/gif/webp/bmp/ico） |
| 其它 | 只做文件级（存在 + 非空 + 扩展名） |

## 占位符审计覆盖的模式

`LOREM IPSUM`、`TODO`/`FIXME`/`XXX`/`TBD`、`占位`/`待补充`/`待填写`/`待定`/`此处省略`、`{placeholder}`/`<your_xxx>`/`[插入…]`/`???`。任一命中即 `passed: false`。

## 输出协议

每次调用 stdout 输出一个 JSON：

```json
{"ok": true,  "tool": "check", "result": {"passed": true, "steps": [...]}, "evidence": {"quote": "…"}}
{"ok": false, "tool": "check", "error": {"code": "FILE_NOT_FOUND", "msg": "…"}}
```

- `ok` 是工具本身是否执行成功；**校验结论看 `result.passed`**（`ok:true` + `passed:false` = 文件有问题）。
- `evidence.quote` 是一句话证据，可直接写进交付说明。
- 错误码：`FILE_NOT_FOUND` / `NOT_A_FILE` / `PARSE_ERROR` / `SYNTAX_ERROR` / `DEP_MISSING` / `BAD_ARGS`。

## 单项子命令（需要更细粒度时）

```bash
verify.py file  <path> --expect-ext .md          # 存在/非空/扩展名
verify.py text  <path> --must-contain 结论        # 空白/占位符/关键词
verify.py json  <path> --must-contain-key name    # JSON 解析 + 键存在
verify.py code  <path>                           # 语法编译（py/js）
verify.py html  <path>                           # 解析 + 正文非空
verify.py image <path>                           # 魔数校验
```

## 交付前流程

1. **定位**：确认待交付文件路径与扩展名。
2. **校验**：对每个产物跑一次 `check`，有关键内容要求时加 `--must-contain`。
3. **引用证据**：交付说明里只引用真实跑过的命令和它的 `evidence.quote`。不要把自己目测的结论说成校验证据。
4. **再交付**：全部 `passed: true` 后才交付；有 `passed: false` 先修产物再重跑。

## 边界

- 这是**结构级**校验（空白/占位符/语法/格式），不替代内容质量判断——「写得对不对」仍由模型读，「存不存在、空不空、假不假」交给脚本。
- `text` 占位符审计对正常含「TODO」的代码交付会误报；这类文件用 `code` 子命令（只查语法）而非 `check`。
- 上游完整版（58 子命令、xlsx/docx/pdf/pptx 支持）见社区 verifier-hub 项目；本技能只保留零依赖、最高频的能力，需要 Office 文档校验时按需扩展 fetcher。
