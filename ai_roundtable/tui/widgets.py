"""可复用部件：折行 Markdown 渲染与主输入框。"""
from rich.markdown import CodeBlock as _CodeBlock
from rich.markdown import Markdown
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.widgets import Input


class FoldingCodeBlock(_CodeBlock):
    """代码块长行折行显示（Rich 默认裁剪超宽行）。"""

    def __rich_console__(self, console, options):
        code = str(self.text).rstrip()
        yield Text(" ", style="on #161b22")
        for line in (code.split("\n") if code else [""]):
            yield Text(" " + line, style="on #161b22",
                       overflow="fold", no_wrap=False)
        yield Text(" ", style="on #161b22")


class FoldingMarkdown(Markdown):
    elements = {**Markdown.elements,
                "fence": FoldingCodeBlock, "code_block": FoldingCodeBlock}


class RoundtableInput(Input):
    """主输入框：↑ 恢复上一条输入 / Ctrl+A 全选 / 多行粘贴折叠 / Ctrl+V 图片粘贴。

    依赖宿主 app 的三个钩子：get_last_input() / register_paste(text) /
    handle_image_paste(img, input)。
    """

    BINDINGS = [
        Binding("ctrl+v", "paste", show=False),
    ]

    def _on_key(self, event: events.Key) -> None:
        # Textual 按 MRO 依次调用各层 _on_key，Input 自身的按键处理不受影响
        if event.key == "ctrl+a":
            event.stop()
            event.prevent_default()
            self.select_all()
            return
        if event.key != "up":
            return
        get_last = getattr(self.app, "get_last_input", None)
        last = get_last() if get_last else ""
        if not last:
            return
        event.stop()
        event.prevent_default()
        self.value = last
        self.cursor_position = len(self.value)

    def action_paste(self) -> None:
        handle_image = getattr(self.app, "handle_image_paste", None)
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is not None and handle_image:
                handle_image(img, self)
                return
        except ImportError:
            self.app.notify("图片粘贴需要 Pillow：pip install Pillow",
                            severity="warning", timeout=5)
        except Exception as e:
            self.app.notify(f"图片读取失败: {e}", severity="error", timeout=5)
        super().action_paste()

    def _on_paste(self, event: events.Paste) -> None:
        text = event.text
        lines = text.splitlines()
        if len(lines) <= 1:
            self.insert_text_at_cursor(text)
        else:
            register = getattr(self.app, "register_paste", None)
            token = register(text) if register else text
            self.insert_text_at_cursor(token)
        event.text = ""
        event.stop()
