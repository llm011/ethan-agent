"""Textual TUI 对话界面。

独立于 CLI 入口，便于测试和复用。
"""
from ethan.core.agent import Agent
from ethan.providers.base import Message

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Input, Markdown, Label


class ChatApp(App):
    """全屏对话 TUI。"""

    CSS = """
    #chat-log {
        height: 1fr;
        overflow-y: auto;
        padding: 1 2;
    }
    #input-bar {
        height: 3;
        padding: 0 2;
    }
    Input {
        width: 100%;
    }
    .user-msg   { color: $success;    margin-bottom: 1; }
    .ethan-msg  { color: $text;       margin-bottom: 1; }
    .thinking   { color: $text-muted; margin-bottom: 1; }
    """

    BINDINGS = [("ctrl+c", "quit", "退出"), ("escape", "quit", "退出")]

    def __init__(self, agent: Agent, initial_prompt: str | None = None):
        super().__init__()
        self._agent = agent
        self._history: list[Message] = []
        self._initial_prompt = initial_prompt

    def compose(self) -> ComposeResult:
        model_id = self._agent._provider.model
        yield Header(show_clock=True)
        yield ScrollableContainer(id="chat-log")
        yield Vertical(
            Input(placeholder=f"输入消息… (model: {model_id})", id="user-input"),
            id="input-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        if self._initial_prompt:
            self.call_after_refresh(self._handle_user_message, self._initial_prompt)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        self.call_after_refresh(self._handle_user_message, text)

    def _append_to_log(self, text: str, css_class: str) -> None:
        log = self.query_one("#chat-log", ScrollableContainer)
        log.mount(Markdown(text, classes=css_class))
        log.scroll_end(animate=False)

    async def _handle_user_message(self, text: str) -> None:
        self._append_to_log(f"**You:** {text}", "user-msg")
        self._history.append(Message(role="user", content=text))

        log = self.query_one("#chat-log", ScrollableContainer)
        thinking = Label("_Ethan 正在思考…_", classes="thinking")
        log.mount(thinking)
        log.scroll_end(animate=False)

        full = ""
        try:
            async for chunk in self._agent.stream_chat(list(self._history)):
                full += chunk
        except Exception as e:
            full = f"**错误：** {e}"
        finally:
            thinking.remove()

        self._append_to_log(f"**Ethan:** {full}", "ethan-msg")
        self._history.append(Message(role="assistant", content=full))
