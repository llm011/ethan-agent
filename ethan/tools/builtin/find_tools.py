"""find_tools 元工具：fast 档只广播少量常驻工具，模型需要更多能力时用它检索并激活长尾工具。

激活后的工具名写入请求级 ACTIVE_TOOLS（ContextVar），agent 主循环下一轮把它们
补进广播给模型的工具清单，模型即可直接调用——避免模型因看不见合适工具而绕路用
terminal 硬凑。

工具描述中英混杂，纯关键词匹配不可靠（"写知识库"可能匹配不到英文描述的 knowledge_add）。
find_tools 本就是"现有工具不够用"时才触发的逃生口、长尾工具仅十余个，故触发时一次性
激活全部非常驻工具并返回完整目录；query 仅用于排序展示，让最相关的排在前面。纯 Python，无模型调用。
"""
import re

from ethan.core.context import activate_tools
from ethan.tools.base import BaseTool
from ethan.tools.registry import ToolRegistry


def _tokenize(text: str) -> list[str]:
    """切出关键词：连续的英文单词 + 单个中文字。"""
    return re.findall(r"[a-zA-Z]+|[一-鿿]", text.lower())


class FindToolsTool(BaseTool):
    fast_path = True
    no_compress = True
    cacheable = False  # 有"激活"副作用，不缓存
    name = "find_tools"
    description = (
        "当现有工具不足以完成任务时调用：激活全部进阶工具（写文件、知识库、定时任务、"
        "密钥管理、记忆/技能写入、代码委派等），并按你给的 query 排序返回工具目录。"
        "激活后即可在后续步骤直接调用列表里的任意工具。不要用 terminal 去硬凑这些能力。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "想做的事或想要的能力，如'写文件''查知识库''发飞书消息'。仅用于排序，不影响激活范围。",
            },
        },
        "required": ["query"],
    }

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def _score(self, tool: BaseTool, query: str, q_tokens: set) -> int:
        haystack = f"{tool.name} {tool.description}".lower()
        score = 0
        if query.strip() and query.strip().lower() in haystack:
            score += 5
        score += len(q_tokens & set(_tokenize(haystack)))
        return score

    async def run(self, query: str) -> str:
        fast_names = {t.name for t in self._registry.all() if t.fast_path}
        extra = [t for t in self._registry.all() if t.name not in fast_names]
        if not extra:
            return "没有可激活的额外工具，当前工具集已是全部。"

        q_tokens = set(_tokenize(query))
        extra.sort(key=lambda t: self._score(t, query, q_tokens), reverse=True)

        # 全部激活：长尾工具仅十余个，触发即升级到全量，避免"搜了却没激活对的工具"。
        activate_tools([t.name for t in extra])

        lines = [f"已激活以下 {len(extra)} 个进阶工具，现在可直接调用（按与「{query}」的相关度排序）："]
        for t in extra:
            lines.append(f"- {t.name}: {t.description}")
        return "\n".join(lines)

