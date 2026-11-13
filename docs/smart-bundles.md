# Ethan Agent 智能技能包系统

## 🎯 设计理念

参考 DSH 和 Pi Agent 的**初始简洁、按需扩展**原则，将技能按使用场景组织成"智能包"，用户根据需求选择启用哪些包。

---

## 📦 智能技能包分类

### 1. Core Bundle（核心包）- 默认启用
**适用场景**: 95% 的日常对话
**大小**: ~200 tokens

包含所有用户每天都会用到的基础能力：
- ✅ 对话管理（会话创建/切换/删除）
- ✅ 文件读写（读取/编辑/保存）
- ✅ Shell 命令执行
- ✅ Web 搜索与抓取
- ✅ 记忆管理（短期/长期记忆）
- ✅ 定时任务创建
- ✅ 知识库基础查询
- ✅ 文件交付

**特点**: 
- 永远在线，无需配置
- 响应极快（< 50ms）
- 占用 Context < 200 tokens

---

### 2. Productivity Bundle（效率包）- 可选启用
**适用场景**: 办公、学习、项目管理
**大小**: ~500 tokens

提升工作效率的高级工具：
- ✅ 浏览器自动化（use-browser）
- ✅ 飞书集成（消息/日历/文档）
- ✅ 文档生成（doc_save）
- ✅ 日程管理（schedule_*）
- ✅ 知识检索（knowledge_*）
- ✅ 文件搜索（rg_search/fd_find）
- ✅ 结构化卡片（ui_card）

**特点**:
- 首次使用时自动提示安装
- 支持一键启用/禁用
- 占用 Context ~500 tokens

---

### 3. Development Bundle（开发包）- 可选启用
**适用场景**: 编程、调试、技术工作
**大小**: ~400 tokens

开发者专属工具集：
- ✅ 代码审查（code-review）
- ✅ 终端操作增强
- ✅ Git 集成
- ✅ API 测试
- ✅ 日志分析
- ✅ 性能 profiling
- ✅ 数据库查询

**特点**:
- 仅在检测到开发环境时推荐
- 支持自定义命令白名单
- 占用 Context ~400 tokens

---

### 4. Creative Bundle（创意包）- 可选启用
**适用场景**: 内容创作、设计、多媒体
**大小**: ~600 tokens

创意工作流工具：
- ✅ PPT 生成（ppt-generate）
- ✅ 文章转视频（article-to-video）
- ✅ 图片处理
- ✅ 音频生成
- ✅ 可视化图表
- ✅ 文案润色
- ✅ 多语言翻译

**特点**:
- 按需加载重型模型
- 支持后台异步处理
- 占用 Context ~600 tokens

---

### 5. Research Bundle（研究包）- 可选启用
**适用场景**: 深度调研、学术分析
**大小**: ~450 tokens

研究型工具集：
- ✅ 深度调研（deep-research）
- ✅ 论文分析（paper-analysis）
- ✅ 数据可视化
- ✅ 引用管理
- ✅ 文献综述
- ✅ 对比分析

**特点**:
- 支持长程任务
- 断点续传
- 占用 Context ~450 tokens

---

### 6. Lifestyle Bundle（生活包）- 可选启用
**适用场景**: 日常生活中的辅助
**大小**: ~350 tokens

生活服务工具：
- ✅ 地图服务（amap-lbs）
- ✅ 火车票查询
- ✅ 天气提醒
- ✅ 购物比价
- ✅ 健康记录
- ✅ 旅行规划

**特点**:
- 实时数据接入
- 位置感知
- 占用 Context ~350 tokens

---

## 🚀 启用策略

### 策略 1: 场景识别（自动）
```python
# 检测用户意图
if "写报告" in prompt or "做 PPT":
    suggest_bundle("creative")
elif "代码" in prompt or "debug":
    suggest_bundle("development")
elif "飞书" in prompt or "开会":
    suggest_bundle("productivity")
```

### 策略 2: 手动选择（推荐）
在设置中提供"技能包管理器"：
```yaml
enabled_bundles:
  - core  # 始终启用
  - productivity
  # - development     # 未启用
  # - creative        # 未启用
```

### 策略 3: 渐进式引导
首次使用时：
1. 展示可用技能包预览
2. 推荐最适合的 2-3 个包
3. 允许用户跳过或自定义

---

## 📊 效果对比

| 方案 | Context 占用 | 启动速度 | 灵活性 | 用户体验 |
|------|------------|---------|--------|---------|
| **全量注入** | ~6KB | 慢 | 低 | 混乱 |
| **智能包** | ~200-800B | 快 | 高 | 清晰 |
| **按需加载** | ~50-200B | 极快 | 极高 | 流畅 |

---

## 🔧 实现示例

### 1. 智能包注册
```python
from ethan.core.bundles import register_bundle, get_enabled_bundles

register_bundle(
    name="core",
    skills=["file_read", "shell", "web_search"],
    auto_enable=True,
)

register_bundle(
    name="productivity",
    skills=["browser_session", "lark_chat", "knowledge_search"],
    auto_enable=False,
    triggers=["飞书", "浏览器", "文档"],
)
```

### 2. 上下文构建优化
```python
def build_context(query: str):
    # 只注入启用的包
    enabled = get_enabled_bundles()
    
    # 核心包总是注入
    context = inject_skills(enabled["core"])
    
    # 其他包按需激活
    for bundle_name in enabled.get("other", []):
        if should_activate(bundle_name, query):
            context += inject_skills(get_bundle(bundle_name))
    
    return context[:MAX_CONTEXT_TOKENS]
```

### 3. 动态加载
```python
async def load_skill_on_demand(skill_name: str):
    """运行时加载技能"""
    if skill_name not in loaded_skills:
        skill = await fetch_skill_from_registry(skill_name)
        registry.register(skill)
        logger.info(f"Loaded skill: {skill_name}")
```

---

## 🎯 最佳实践

### ✅ 推荐做法
1. **Core 永远启用** - 保证基础体验
2. **Productivity 默认推荐** - 覆盖 70% 场景
3. **Specialized 按需触发** - 减少干扰
4. **用户可完全控制** - 设置中随时调整

### ❌ 避免做法
1. ~~一次性注入所有技能~~
2. ~~强制启用不需要的包~~
3. ~~隐藏启用/禁用选项~~
4. ~~缺乏清晰的场景分类~~

---

## 📝 迁移指南

### 从旧版本迁移
1. 扫描现有技能使用情况
2. 自动归类到对应智能包
3. 保留高频技能在 Core
4. 低频技能移至 Specialized

### 用户配置迁移
```bash
# 旧格式
skills: [file_read, shell, web_search, browser_session, ...]

# 新格式
bundles:
  core: true
  productivity: true
  development: false
  creative: false
```

---

**版本**: v1.0  
**最后更新**: 2026-11-14  
**目标**: 极致简洁 + 强大灵活
