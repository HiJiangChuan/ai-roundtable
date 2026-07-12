"""类型化事件：core 层与 UI 之间的唯一通信协议。

每个事件都携带 session_id，UI 据此路由到对应 tab——
后台 tab 的活动只更新其自己的缓冲区，不会串台。
"""
from dataclasses import dataclass, field
from typing import Callable, Dict

# role 取值：guest / moderator / quick / compare / history


@dataclass
class Event:
    session_id: str


@dataclass
class AgentStarted(Event):
    agent: str = ""
    role: str = "guest"
    round: int = 0


@dataclass
class AgentDelta(Event):
    """流式输出片段（仅用于实时预览，不持久化）。"""
    agent: str = ""
    text: str = ""


@dataclass
class AgentProgress(Event):
    """工具调用/stderr 进度行（仅展示）。"""
    agent: str = ""
    line: str = ""


@dataclass
class AgentIdle(Event):
    agent: str = ""
    elapsed: float = 0.0


@dataclass
class AgentResponded(Event):
    agent: str = ""
    content: str = ""
    role: str = "guest"
    round: int = 0
    extra: str = ""     # role=direct 时为用户的原始提问


@dataclass
class ModeratorParsed(Event):
    """主持人综述的结构化结果（矛盾点/下一问/行动分配/本轮摘要）。"""
    moderator: str = ""
    round: int = 0
    sections: Dict[str, str] = field(default_factory=dict)


@dataclass
class StatusChanged(Event):
    state: str = "ready"   # running / ready / ended
    message: str = ""


@dataclass
class TitleGenerated(Event):
    title: str = ""


@dataclass
class SessionEnded(Event):
    summary: str = ""


@dataclass
class ErrorOccurred(Event):
    message: str = ""


EmitFn = Callable[[Event], None]
