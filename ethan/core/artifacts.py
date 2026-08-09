"""会话工件（Artifacts）追踪 —— 从对话历史中提取已生成/交付的文件，
在每轮对话开头注入精简清单，让模型无需重新生成即可通过 file_read 引用。

背景问题：
- 工具调用产生的 /tmp 文件路径主要出现在 tool result 中，而 tool 消息不跨请求持久化
- deliver_file 的卡片虽然持久化在 assistant 消息的 cards 字段，但模型看不到 cards 数据
- web_fetch 长内容 offload 到 /tmp 后，路径标记在下一轮可能被 context_budget 驱逐

本模块解决方式：
1. 每次 agent.chat() 入口，扫描传入的 messages 列表：
   - 从所有 assistant 消息的 cards 中提取 type="file" 的文件卡片（含 path/title/kind）
   - 正则扫描所有消息 content 中的文件路径标记（web_fetch offload、deliver_file 路径提示等）
2. 去重后构建精简清单，作为 user 消息注入到 working 末尾（当前用户问题之前），
   告诉模型「本会话已有这些文件可用，可直接 file_read」。
3. 注入的提示是幂等的：重复调用不会重复追加（检查标记）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ethan.providers.base import Message

# 注入标记：防止重复注入
_ARTIFACTS_MARKER = "[本对话可用文件清单]"

# 匹配文件路径的正则：
# - 绝对路径，以 / 开头
# - 允许常见文件扩展名（.md/.txt/.pdf/.docx/.pptx/.xlsx/.csv/.html/.json/.png/.jpg/.jpeg/.gif/.webp/.svg/.zip）
# - 路径中不含空白字符和常见标点
_FILE_PATH_RE = re.compile(
    r"(/[^\s`\"'<>|]+\.(?:md|txt|pdf|docx|pptx|xlsx|csv|html|json|png|jpg|jpeg|gif|webp|svg|zip))",
    re.IGNORECASE,
)

# 从工具输出中提取「文件路径说明」上下文的正则：
# 匹配类似「保存到文件 /tmp/xxx.md」「文件路径：/tmp/xxx.md」「读取 /tmp/xxx.md」等模式
# 取路径前 40 个字符作为简短说明
_DESC_CONTEXT_CHARS = 60


@dataclass
class Artifact:
    """一个已生成/交付的文件工件。"""
    path: str
    title: str = ""
    kind: str = ""
    description: str = ""  # 从上下文提取的简短说明

    def dedup_key(self) -> str:
        return self.path


def extract_artifacts(messages: list[Message]) -> list[Artifact]:
    """从消息列表中提取所有文件工件，去重后返回。

    提取来源：
    1. assistant 消息的 cards 字段（type="file" 的卡片，含 path/title/kind）
    2. 所有消息 content 中的文件路径（正则匹配）
    """
    artifacts: dict[str, Artifact] = {}

    for msg in messages:
        # 1. 从 cards 中提取
        if msg.cards:
            for card in msg.cards:
                if not isinstance(card, dict):
                    continue
                if card.get("type") != "file":
                    continue
                path = card.get("path", "")
                if not path:
                    continue
                if path not in artifacts:
                    artifacts[path] = Artifact(
                        path=path,
                        title=card.get("title", "") or card.get("filename", ""),
                        kind=card.get("kind", ""),
                    )
                else:
                    # 已存在则补全缺失字段
                    a = artifacts[path]
                    if not a.title and card.get("title"):
                        a.title = card["title"]
                    if not a.kind and card.get("kind"):
                        a.kind = card["kind"]

        # 2. 从 content 中用正则提取路径
        content = msg.content or ""
        if not content:
            continue
        for m in _FILE_PATH_RE.finditer(content):
            path = m.group(1)
            if path in artifacts:
                # 已有该文件，尝试补充 description
                if not artifacts[path].description:
                    artifacts[path].description = _extract_context_description(content, m.start(), path)
                continue
            # 新文件：从上下文提取简短说明
            desc = _extract_context_description(content, m.start(), path)
            # 尝试从路径猜文件名作为 title
            title = path.split("/")[-1] if "/" in path else path
            kind = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            artifacts[path] = Artifact(path=path, title=title, kind=kind, description=desc)

    return list(artifacts.values())


def _extract_context_description(content: str, match_start: int, path: str) -> str:
    """从路径匹配位置前后提取简短说明文字。"""
    # 往前找最多 DESC_CONTEXT_CHARS 字符，截取到行首或标点为止
    start = max(0, match_start - _DESC_CONTEXT_CHARS)
    prefix = content[start:match_start]
    # 取最后一个换行/句号/分号之后的内容作为说明
    for sep in ["\n", "。", "；", ";", ".", "】", "]"]:
        idx = prefix.rfind(sep)
        if idx >= 0:
            prefix = prefix[idx + 1:]
            break
    prefix = prefix.strip()
    if prefix:
        return prefix[:80]
    return ""


def build_artifacts_prompt(artifacts: list[Artifact]) -> str:
    """构建文件清单提示文本。"""
    if not artifacts:
        return ""
    lines = [f"{_ARTIFACTS_MARKER}"]
    lines.append("本轮对话之前已生成/获取以下文件，可直接用 file_read 工具读取，无需重新生成或获取：")
    for a in artifacts:
        name = a.title or a.path.split("/")[-1]
        desc = f" — {a.description}" if a.description else ""
        lines.append(f"- {name}：{a.path}{desc}")
    lines.append("如需使用上述文件内容，直接用 file_read 读取对应路径即可。")
    return "\n".join(lines)


def already_injected(messages: list[Message]) -> bool:
    """检查 messages 中是否已有工件清单标记（防重复注入）。"""
    for msg in messages:
        if msg.role == "user" and msg.content and _ARTIFACTS_MARKER in msg.content:
            return True
    return False


def inject_artifacts_prompt(messages: list[Message]) -> None:
    """就地为 messages 注入文件清单提示（如果有工件且未注入过）。

    注入位置：在最后一条 user 消息之前插入一条 user 消息，避免干扰当前用户问题。
    如果最后一条不是 user 消息，则追加到末尾。
    """
    if already_injected(messages):
        return
    artifacts = extract_artifacts(messages)
    if not artifacts:
        return
    prompt = build_artifacts_prompt(artifacts)
    if not prompt:
        return

    artifact_msg = Message(role="user", content=prompt)
    # 找到最后一条 user 消息，在它之前插入
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user_idx = i
            break
    if last_user_idx >= 0:
        messages.insert(last_user_idx, artifact_msg)
    else:
        messages.append(artifact_msg)
