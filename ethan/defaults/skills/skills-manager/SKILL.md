---
name: skills-manager
description: "管理 Agent 技能包：搜索、安装、更新、卸载 Skills。使用 npx skills 工具，支持从 GitHub 或 npm 安装社区 skill。"
trigger: "install skill|add skill|skills list|skills find|安装技能|添加技能|技能管理|npx skills|skill 包|search skills"
---

# skills-manager

使用 `npx skills` 工具管理 Agent 的技能包，支持从 GitHub 仓库或 npm 包安装 Skill。

## 查找技能

```bash
# 交互式搜索可用技能
npx skills find

# 搜索关键词
npx skills find github
```

## 安装技能

```bash
# 从 GitHub 仓库安装（指定 skill 名称）
npx skills add https://github.com/owner/repo --skill skillname

# 安装到全局（所有项目共享）
npx skills add https://github.com/owner/repo --skill skillname --global

# 安装到当前项目
npx skills add https://github.com/owner/repo --skill skillname --project
```

安装后，skill 文件会出现在 `~/.ethan/skills/` 目录（用户级）。

## 列出已安装技能

```bash
npx skills list
```

## 更新技能

```bash
# 更新所有技能
npx skills update

# 更新指定技能
npx skills update skillname
```

## 卸载技能

```bash
npx skills remove skillname
```

## 安装 Ethan 内置技能之外的扩展

如果用户想安装一个新 skill：
1. 先用 `npx skills find` 或 GitHub 搜索找到 skill 包地址
2. 用 `npx skills add <url> --skill <name>` 安装
3. 安装后在 `~/.ethan/skills/` 里会生成对应目录
4. 无需重启，下次对话自动加载

## 注意

- `npx skills` 需要 Node.js 环境
- Ethan 内置技能在 `ethan/skills/` 目录（随代码发布），用户安装的在 `~/.ethan/skills/`
- 同名用户技能会覆盖内置技能（方便定制）
