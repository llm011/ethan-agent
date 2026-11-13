# Ethan Agent v2 - 智能助手重构版

> **极简启动 · 场景感知 · 实时反馈 · 编程专家**

[![Version](https://img.shields.io/pypi/v/ethan-agent)](https://pypi.org/project/ethan-agent/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)

---

## 🚀 核心特性

### ✨ 极简启动
- **Core Bundle**: ~150 tokens 基础能力，5 秒内开始对话
- **零配置**: 开箱即用，无需复杂设置
- **渐进增强**: 按需加载高级功能

### 🧠 场景感知
- **智能识别**: 自动检测开发/创意/研究/工作场景
- **动态 Context**: 只注入必要的技能，减少 97% 占用
- **优雅降级**: 工具不可用时自动 fallback

### ⚡ 实时反馈
- **进度可视化**: 阶段总结 + 实时进度条
- **中间结果**: 长程任务分步展示
- **性能监控**: 完整可观测性

### 💻 编程专家
- **全栈工具链**: 代码读写/运行/调试/测试/审查
- **多语言支持**: Python/JavaScript/TypeScript/Go 等
- **智能辅助**: 补全/解释/重构/安全扫描

### 🔌 多内核切换
- **DSH Kernel**: DeepSeek Harness（高性能）
- **Claude SDK**: Anthropic Claude（高质量）
- **Pi Style**: 极简交互风格
- **无缝切换**: 运行时热切换，零停机

---

## 📦 快速开始

### 安装

```bash
pip install ethan-agent
```

### 首次运行

```bash
ethan serve
```

应用会自动：
1. 加载 Core Bundle（基础能力）
2. 检测系统环境
3. 启动默认内核（DSH）
4. 监听端口 8900

### 切换到其他内核

编辑 `~/.ethan/config.yaml`:

```yaml
kernel:
  type: claude_sdk  # 可选：dsh, claude_sdk, pi_style
  
claude_config:
  model: "claude-3-opus-20240229"
  api_key_env: "ANTHROPIC_API_KEY"
```

重启服务即可切换。

---

## 🎯 使用场景

### 日常对话（Instant Mode）
```python
# 仅使用 Core Bundle (~150 tokens)
用户："今天天气怎么样？"
Ethan: "今天晴，25°C..."
```

### 工作效率（Flow Mode）
```python
# 自动启用 Flow Bundle (~600 tokens)
用户："飞书上发个消息给团队，说明天开会"
Ethan: [自动加载 lark_chat 工具]
      → 发送消息 → 返回确认
```

### 深度任务（Power Mode）
```python
# 按需加载 Power Bundles (~2000 tokens)
用户："帮我分析这篇论文并生成报告"
Ethan: [加载 deep_research + paper_analysis]
      → 分阶段执行 → 实时反馈 → 生成报告
```

### 编程任务
```python
# 专业编程助手
用户："写个 Python 脚本，读取 CSV 并画图"
Ethan: [code_read + code_write + shell]
      → 生成代码 → 运行测试 → 返回结果
```

---

## 🛠️ 架构亮点

### 分层设计
```
Presentation Layer (UI)
    ↓
Service Layer (业务逻辑)
    ↓
Domain Layer (领域模型)
    ↓
Infrastructure Layer (基础设施)
```

### 事件驱动
- 轻量级事件总线
- 异步非阻塞
- 完整可观测性

### 插件化
- 热插拔技能包
- 运行时动态加载
- 零停机更新

---

## 📊 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 启动时间 | < 1s | 冷启动 |
| Context 占用 | < 300 tokens | 平均 |
| 首字延迟 | < 200ms | P95 |
| 代码生成 | < 2s | 简单任务 |
| 长程任务恢复 | < 5s | 断点续传 |

---

## 📖 文档导航

- **[架构设计](docs/architecture-v2.md)** - 详细架构说明
- **[技能包系统](docs/smart-bundles.md)** - 场景化技能管理
- **[内核切换](docs/kernel-switching.md)** - 多内核支持
- **[API 参考](docs/api-reference.md)** - 完整 API 文档
- **[最佳实践](docs/best-practices.md)** - 使用指南

---

## 🤝 贡献指南

### 开发环境

```bash
# 克隆仓库
git clone https://github.com/llm011/ethan-agent
cd ethan-agent

# 安装依赖
uv sync --extra dev

# 运行测试
pytest tests/ -v

# 运行 lint
ruff check .
mypy ethan/
```

### 提交 PR

1. Fork 仓库
2. 创建 feature branch (`feature/amazing-feature`)
3. 提交变更 (`git commit -m 'add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 打开 Pull Request

---

## 📄 License

MIT License - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

感谢所有贡献者和用户！

特别感谢：
- DeepSeek Harness 团队（架构灵感）
- Anthropic（Claude SDK）
- Pi AI（交互体验）
- 所有开源项目

---

**版本**: v0.5.395  
**构建**: 2026-11-14  
**维护**: Ethan Team

