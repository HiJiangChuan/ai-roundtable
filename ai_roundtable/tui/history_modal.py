"""Ctrl+O 历史会话选择弹窗：左列 Quick / 右列 Deep。"""
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

_MAX_ROWS = 15


class HistoryModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("enter", "select", show=False),
    ]

    CSS = """
    HistoryModal {
        align: center middle;
        background: #000000 60%;
    }
    #modal-container {
        width: 90;
        height: auto;
        max-height: 36;
        background: #161b22;
        border: solid #30363d;
        padding: 1 2;
    }
    #modal-title {
        height: 1;
        color: #58a6ff;
        margin-bottom: 1;
    }
    #modal-columns {
        height: auto;
        max-height: 28;
    }
    .col-panel {
        width: 1fr;
        height: auto;
        max-height: 28;
        padding: 0 1;
    }
    .col-panel-left {
        border-right: solid #30363d;
        padding-right: 2;
    }
    .col-header {
        height: 1;
        color: #58a6ff;
        margin-bottom: 0;
    }
    .col-header.--active {
        color: #e6edf3;
    }
    .session-item {
        height: 1;
        color: #8b949e;
        padding: 0 1;
    }
    .session-item.--highlight {
        background: #1f6feb;
        color: #e6edf3;
    }
    .col-empty, .col-more {
        color: #3d444d;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, sessions: list):
        super().__init__()
        self._quick = [s for s in sessions if s["type"] == "quick"]
        self._deep = [s for s in sessions if s["type"] == "deep"]
        self._col = 0 if self._quick else (1 if self._deep else 0)
        self._rows = [0, 0]

    def _col_list(self, col: int) -> list:
        return self._quick if col == 0 else self._deep

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Static("历史对话   ↑↓ 选择   ←→ 切换   Enter 打开   Esc 关闭",
                         id="modal-title")
            with Horizontal(id="modal-columns"):
                for col, (label, items) in enumerate(
                        [("⚡ Quick Round", self._quick),
                         ("🔬 Deep Round", self._deep)]):
                    classes = "col-panel col-panel-left" if col == 0 else "col-panel"
                    with Vertical(classes=classes):
                        hdr = "col-header --active" if self._col == col else "col-header"
                        yield Static(label, id=f"col-hdr-{col}", classes=hdr)
                        if items:
                            for i, s in enumerate(items[:_MAX_ROWS]):
                                hi = (self._col == col and i == 0)
                                cls = "session-item --highlight" if hi else "session-item"
                                yield Static(self._fmt(s, col),
                                             id=self._item_id(col, i), classes=cls)
                            if len(items) > _MAX_ROWS:
                                yield Static(f"…还有 {len(items) - _MAX_ROWS} 条",
                                             classes="col-more")
                        else:
                            yield Static("暂无记录", classes="col-empty")

    @staticmethod
    def _fmt(s: dict, col: int) -> str:
        unit = "条" if col == 0 else "轮"
        date = s.get("date", "")
        date = date[5:] if len(date) == 10 else date        # MM-DD
        return f"{date}  {s['title'][:26]}  ({s.get('entries', 0)}{unit})"

    @staticmethod
    def _item_id(col: int, row: int) -> str:
        return f"q-{row}" if col == 0 else f"d-{row}"

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key in ("up", "down"):
            items = self._col_list(self._col)
            if not items:
                return
            n = min(len(items), _MAX_ROWS)
            old = self._rows[self._col]
            new = (old + (-1 if key == "up" else 1)) % n
            self._rows[self._col] = new
            self.query_one(f"#{self._item_id(self._col, old)}",
                           Static).set_classes("session-item")
            self.query_one(f"#{self._item_id(self._col, new)}",
                           Static).set_classes("session-item --highlight")
        elif key in ("left", "right"):
            target = 1 if key == "right" else 0
            if target == self._col:
                return
            old_items = self._col_list(self._col)
            if old_items:
                row = self._rows[self._col]
                self.query_one(f"#{self._item_id(self._col, row)}",
                               Static).set_classes("session-item")
            self.query_one(f"#col-hdr-{self._col}",
                           Static).set_classes("col-header")
            self._col = target
            self.query_one(f"#col-hdr-{self._col}",
                           Static).set_classes("col-header --active")
            new_items = self._col_list(self._col)
            if new_items:
                row = self._rows[self._col]
                self.query_one(f"#{self._item_id(self._col, row)}",
                               Static).set_classes("session-item --highlight")

    def action_select(self) -> None:
        items = self._col_list(self._col)
        self.dismiss(items[self._rows[self._col]] if items else None)
