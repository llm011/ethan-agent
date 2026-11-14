# Ethan Agent 深度优化计划

> ⚠️ **历史规划文档，非验收报告**（2026-11-14 标注）
>
> 本文写于一次重构之前，文中的「预期效果」「-92%」「-80%」等数字是**当时的目标推测**，
> 不是实测结果，也未全部落地。v2 第一轮曾据此类数字声称完成，核实后发现多处为零引用
> 的假实现，详见 `ETHAN_V2_RESTRUCTURE_PLAN.md`。
>
> 特别是「Context 占用 ~6KB → ~300B」这个前提本身是错的：真实的 6KB 级占用不在技能包，
> 而在 `~/.ethan/system/tools.md`（`tools_reference`）与技能全量描述表。当前 system prompt
> 的**实测**体积请以唯一可信入口为准：
>
> ```bash
> .venv/bin/python -m tests.bench_prompt_size          # 各块字符数 + 体积护栏
> .venv/bin/python -m pytest tests/test_prompt_budget.py -q
> ```
>
> 截至 2026-11-14 实测：full 档 system prompt 51,954 字符（≈17.3K tokens），其中
> `tools_reference` 34,317 字符占 66%；技能分级已落地（12.9K → 4.5K），但
> `tools.md` 的结构性拆分仍是 P1 待办，尚未完成。

## 🎯 优化目标

1. **极致精简** - 减少 80% 的无用技能注入
2. **DSH 架构重构** - 学习 DSH 内核设计
3. **长程任务支持** - 断点续传、长时间运行
4. **智能渲染优化** - 结构化展示、过程可视化
5. **性能提升** - 启动速度 +50%，响应速度 +30%

---

## 📊 当前问题分析

### 1. 技能注入冗余
- **问题**: 64 个技能，每个平均 100 行，每次对话注入 ~6KB
- **影响**: 占用大量 context window，降低 LLM 判断力
- **解决**: 
  - 核心技能（10 个）完整注入
  - 中频技能（10 个）按需激活
  - 低频技能（40+ 个）完全移除默认注入

### 2. 缺少长程任务机制
- **问题**: 模型抖动导致任务中断，无法恢复
- **影响**: 复杂任务失败率高，用户体验差
- **解决**: 
  - 实现 Task State Machine
  - 持久化任务状态
  - 断点续传机制

### 3. 渲染方式落后
- **问题**: 纯文本输出，缺乏结构化展示
- **影响**: 信息密度低，阅读体验差
- **解决**: 
  - A2UI 卡片增强
  - Markdown 表格优化
  - 进度条/步骤可视化

### 4. 心理模型无用
- **问题**: Claude/Codex 等心理模型占用 token
- **影响**: 实际使用频率 < 1%
- **解决**: 全部移除

---

## 🚀 实施计划

### Phase 1: 技能精简（立即执行）✅

#### 1.1 核心技能识别
```python
CORE_SKILLS = {
    "ui-card",           # 结构化卡片
    "agent-browser",     # 浏览器自动化
    "use-browser",       # 本机浏览器
    "knowledge-*",       # 知识库管理
    "schedule-*",        # 定时任务
    "file-read/write",   # 文件操作
    "shell",             # 命令执行
    "web-search/fetch",  # 网络搜索
    "lark-*",            # 飞书集成
    "deep-research",     # 深度调研
}
```

#### 1.2 技能压缩策略
- **Core Skills**: 完整保留，但压缩 description 至 100 字内
- **Medium Skills**: 仅注入 trigger + 一句话描述 (< 50 tokens)
- **Low Frequency**: 完全不注入，通过 `find_tools` 按需加载
- **Deprecated**: 直接删除

#### 1.3 预期效果
- 技能注入量：6KB → 500 bytes (**减少 92%**)
- Context 节省：每轮对话节省 ~500 tokens
- LLM 判断力提升：更专注核心能力

---

### Phase 2: DSH 架构重构（本周完成）

#### 2.1 DSH 核心设计理念
1. **插件化架构** - 所有功能都是插件，热插拔
2. **声明式配置** - YAML 定义行为，代码自动执行
3. **增量更新** - 只处理变化的部分，避免全量重算
4. **异步优先** - 所有 I/O 异步，非阻塞
5. **状态持久化** - 所有状态可序列化、可恢复

#### 2.2 Ethan 架构改造
```
Before (Monolithic):
├── ethan/
│   ├── core/          # 混合逻辑
│   ├── tools/         # 工具散乱
│   └── skills/        # 技能平铺

After (DSH-like):
├── ethan/
│   ├── kernel/        # 核心引擎
│   │   ├── scheduler/ # 任务调度器
│   │   ├── state/     # 状态管理
│   │   └── plugin/    # 插件系统
│   ├── plugins/       # 插件目录
│   │   ├── browser/   # 浏览器插件
│   │   ├── lark/      # 飞书插件
│   │   └── ...
│   └── config.yaml    # 声明式配置
```

#### 2.3 关键改进
1. **插件系统** - 所有工具/skill 都变成插件
2. **配置驱动** - 通过 YAML 配置行为，无需改代码
3. **热重载** - 修改配置即时生效，无需重启
4. **版本管理** - 插件版本控制，兼容性强

---

### Phase 3: 长程任务机制（下周完成）

#### 3.1 Task State Machine
```python
class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class LongRunningTask:
    def __init__(self, task_id: str, prompt: str):
        self.id = task_id
        self.prompt = prompt
        self.state = TaskState.PENDING
        self.checkpoints = []  # 断点记录
        self.context_snapshot = None  # 上下文快照
        
    def save_checkpoint(self, step: int, data: dict):
        """保存断点"""
        self.checkpoints.append({
            "step": step,
            "timestamp": time.time(),
            "data": data,
            "context": self.context_snapshot,
        })
        
    def resume_from(self, checkpoint_index: int = -1):
        """从断点恢复"""
        checkpoint = self.checkpoints[checkpoint_index]
        self.state = TaskState.RESUMING
        self.context_snapshot = checkpoint["context"]
        return checkpoint["data"]
```

#### 3.2 持久化存储
- **SQLite**: 存储任务状态和检查点
- **Redis**: 缓存活跃任务状态
- **Object Storage**: 存储大文件检查点

#### 3.3 容错机制
- **自动重试**: 失败后自动重试（最多 3 次）
- **超时保护**: 长时间无响应自动暂停
- **人工介入**: 关键节点请求用户确认

---

### Phase 4: 渲染优化（持续进行）

#### 4.1 A2UI 卡片增强
```yaml
card:
  type: timeline
  items:
    - title: "阶段 1"
      status: completed
      progress: 100%
    - title: "阶段 2"
      status: running
      progress: 60%
    - title: "阶段 3"
      status: pending
      progress: 0%
```

#### 4.2 进度可视化
```
✅ 已完成：3/10
⏳ 进行中：4/10
⏸️ 待处理：3/10

[████████░░░░] 40%
```

#### 4.3 结构化输出
- **表格**: 对比数据、列表项
- **代码块**: 语法高亮
- **引用**: 引用来源标注
- **链接**: 可点击跳转

---

### Phase 5: 移除无用心理模型（立即执行）

#### 5.1 需要移除的心理模型
```python
DEPRECATED_MIND_MODELS = [
    "苏念陪伴模式",      # 情感陪伴，不用
    "Claude 风格",       # 已废弃
    "Codex 模式",        # 已废弃
    "QA 证据链",         # 测试专用
    "Karpathy Wiki",    # 低频维护
]
```

#### 5.2 替换方案
- **情感陪伴**: 使用通用回复模板
- **风格控制**: 通过 system prompt 控制
- **测试验证**: 使用标准测试框架

---

## 📈 预期效果

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| **技能注入量** | 6KB | 500B | **-92%** ⚡ |
| **Context 占用** | ~5000 tokens | ~1000 tokens | **-80%** ⚡ |
| **启动速度** | ~2s | ~1s | **+50%** ⚡ |
| **响应速度** | ~500ms | ~350ms | **+30%** ⚡ |
| **任务成功率** | ~70% | ~95% | **+25%** ✅ |
| **内存占用** | ~150MB | ~100MB | **-33%** 💾 |

---

## 🔧 技术细节

### 技能压缩算法
```python
def compress_skill(skill: Skill) -> Skill:
    """压缩技能内容"""
    skill.description = truncate_to_tokens(skill.description, max_tokens=100)
    skill.trigger = skill.trigger[:5]  # 最多 5 个关键词
    
    # 移除 references 中的重复项
    skill.references = deduplicate_references(skill.references)
    
    # 压缩 content 至 3000 chars
    if len(skill.content) > 3000:
        skill.content = skill.content[:3000] + "..."
    
    return skill
```

### 任务状态机
```python
class TaskStateMachine:
    def __init__(self):
        self.states = {
            TaskState.PENDING: self._on_pending,
            TaskState.RUNNING: self._on_running,
            TaskState.PAUSED: self._on_paused,
            TaskState.COMPLETED: self._on_completed,
            TaskState.FAILED: self._on_failed,
        }
        
    def transition(self, from_state: TaskState, to_state: TaskState):
        """状态转换"""
        if from_state in self.states:
            self.states[from_state](to_state)
            
    def _on_running(self, next_state):
        """运行时处理"""
        if self._should_checkpoint():
            self.save_checkpoint()
        elif self._is_timeout():
            self.pause()
```

---

## 📝 下一步行动

1. **立即执行**: 技能过滤脚本运行
2. **本周完成**: DSH 架构重构原型
3. **下周完成**: 长程任务机制
4. **持续优化**: 渲染和展示层

---

**开始时间**: 2026-11-14  
**预计完成**: 2026-11-21  
**优先级**: 🔴 最高
