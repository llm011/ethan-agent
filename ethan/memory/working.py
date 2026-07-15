"""工作记忆 — 管理发送给 LLM 的 context 窗口。

三层滑动窗口：
  热区（hot）: 最近 N 轮完整保留
  温区（warm）: 较早的对话压缩成 rolling summary
  冷区（cold）: 跨 session 的 key facts（持久记忆）

发送给 LLM 的 messages = [冷区摘要] + [温区 summary] + [热区原文]
"""
from dataclasses import dataclass, field

from ethan.providers.base import Message


@dataclass
class MemoryConfig:
    hot_size: int = 5          # 热区保留轮数（1轮 = user + assistant）
    compress_batch: int = 5    # 攒够多少轮再触发一次压缩
    warm_capacity: int = 10    # 温区累积多少轮后触发冷区提取（A3: 从 20 降到 10，短对话也能触发抽取）


@dataclass
class WorkingMemory:
    """维护当前 session 的分层记忆状态。"""

    config: MemoryConfig = field(default_factory=MemoryConfig)

    # 热区：最近的完整消息
    hot: list[Message] = field(default_factory=list)

    # 待压缩缓冲区：从热区溢出但还没压缩的消息
    _compress_buffer: list[Message] = field(default_factory=list)

    # 温区：rolling summary 文本
    warm_summary: str = ""

    # 温区已累积的轮数（用于判断何时触发冷区提取）
    _warm_rounds: int = 0

    # 冷区：key facts（从持久存储加载）
    cold_facts: str = ""

    def add_turn(self, user_msg: Message, assistant_msg: Message) -> None:
        """添加一轮对话到热区，必要时溢出到压缩缓冲。"""
        self.hot.append(user_msg)
        self.hot.append(assistant_msg)

        # 计算当前热区轮数（每 2 条消息 = 1 轮）
        hot_rounds = len(self.hot) // 2
        while hot_rounds > self.config.hot_size:
            # 把最老的一轮移到压缩缓冲
            oldest_user = self.hot.pop(0)
            oldest_assistant = self.hot.pop(0)
            self._compress_buffer.append(oldest_user)
            self._compress_buffer.append(oldest_assistant)
            hot_rounds -= 1

    @classmethod
    def from_history(cls, history: list[Message], cold_facts: str = "", hot_size: int = 10) -> "WorkingMemory":
        """从历史消息构建 WorkingMemory：配对 user/assistant，取最近 hot_size 轮进热区。

        消除 chat/lark/repl/completions 六处重复的「遍历 history 配对 append」逻辑。
        """
        memory = cls(config=MemoryConfig(hot_size=hot_size))
        memory.cold_facts = cold_facts
        hist_ua = [m for m in history if m.role in ("user", "assistant")]
        pairs: list[tuple[Message, Message]] = []
        i = 0
        while i < len(hist_ua) - 1:
            if hist_ua[i].role == "user" and hist_ua[i + 1].role == "assistant":
                pairs.append((hist_ua[i], hist_ua[i + 1]))
                i += 2
            else:
                i += 1
        for u, a in pairs[-hot_size:]:
            memory.hot.append(u)
            memory.hot.append(a)
        return memory

    def needs_compression(self) -> bool:
        """压缩缓冲区是否攒够了一批。"""
        buffer_rounds = len(self._compress_buffer) // 2
        return buffer_rounds >= self.config.compress_batch

    def get_compress_batch(self) -> list[Message]:
        """取出待压缩的消息（调用后清空缓冲区）。"""
        batch = list(self._compress_buffer)
        self._compress_buffer.clear()
        return batch

    def apply_summary(self, new_summary: str) -> None:
        """压缩完成后，更新温区 summary。"""
        if self.warm_summary:
            self.warm_summary = f"{self.warm_summary}\n\n{new_summary}"
        else:
            self.warm_summary = new_summary
        self._warm_rounds += self.config.compress_batch

    def needs_cold_extraction(self) -> bool:
        """温区是否累积够了，需要提取冷区 key facts。"""
        return self._warm_rounds >= self.config.warm_capacity

    def apply_cold_extraction(self, key_facts: str, condensed_summary: str) -> None:
        """冷区提取完成后，更新冷区 facts 并精简温区。"""
        self.cold_facts = key_facts
        self.warm_summary = condensed_summary
        self._warm_rounds = 0

    def build_context(self) -> list[Message]:
        """构建最终发送给 LLM 的 messages 列表。"""
        context: list[Message] = []

        # 冷区 key facts 作为 system context
        if self.cold_facts:
            context.append(Message(
                role="user",
                content=f"[长期记忆] {self.cold_facts}",
            ))
            context.append(Message(
                role="assistant",
                content="好的，我已记住这些信息。",
            ))

        # 温区 summary
        if self.warm_summary:
            context.append(Message(
                role="user",
                content=f"[之前的对话摘要] {self.warm_summary}",
            ))
            context.append(Message(
                role="assistant",
                content="好的，我了解了之前的对话内容。",
            ))

        # 热区原文
        context.extend(self.hot)

        return context

    def total_rounds(self) -> int:
        """总对话轮数（热区 + 缓冲区 + 已压缩的）。"""
        return len(self.hot) // 2 + len(self._compress_buffer) // 2 + self._warm_rounds
