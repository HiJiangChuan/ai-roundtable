"""Prompt 模板加载与渲染。

PromptLoader：用户目录优先，单个文件缺失时回退包内默认。
下方的 render_* 帮助函数是模板变量的唯一契约——所有调用点都必须走它们，
tests/test_prompts.py 会用真实模板逐一渲染这些函数，模板与代码脱节会立刻爆测试。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

from ..config import PKG_PROMPTS_DIR

REQUIRED_PROMPTS = ["opening", "guest", "guest_quick", "moderator",
                    "compare", "compress", "solo_roundtable"]

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class PromptLoader:
    def __init__(self, prompts_dir: Path, fallback_dir: Path = PKG_PROMPTS_DIR):
        self.prompts_dir = Path(prompts_dir)
        self.fallback_dir = Path(fallback_dir)
        self._cache: Dict[str, str] = {}

    def path_for(self, name: str) -> Path:
        """当前生效的模板文件路径（用户目录优先）。"""
        user = self.prompts_dir / f"{name}.md"
        return user if user.exists() else self.fallback_dir / f"{name}.md"

    def _load(self, name: str) -> str:
        if name not in self._cache:
            path = self.path_for(name)
            if not path.exists():
                raise FileNotFoundError(f"Prompt template not found: {path}")
            self._cache[name] = path.read_text(encoding="utf-8")
        return self._cache[name]

    def invalidate(self, name: Optional[str] = None) -> None:
        """模板被编辑后清缓存。"""
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    def render(self, name: str, variables: Dict[str, str]) -> str:
        result = self._load(name)
        for key, value in variables.items():
            result = result.replace("{{" + key + "}}",
                                    str(value) if value is not None else "")
        remaining = _PLACEHOLDER.findall(result)
        if remaining:
            raise ValueError(
                f"Prompt '{name}' has unresolved placeholders: {remaining}")
        return result

    def check_all(self) -> List[str]:
        """返回用户目录和包内都找不到的模板名列表。"""
        return [name for name in REQUIRED_PROMPTS
                if not self.path_for(name).exists()]


# ── 渲染契约 ──────────────────────────────────────────────────────────────────
# 每个模板一个函数，签名即变量集合。新增/删除模板变量必须同步改这里。

def render_guest_quick(pl: PromptLoader, *, agent_name: str, question: str,
                       context_history: str) -> str:
    return pl.render("guest_quick", {
        "agent_name": agent_name,
        "question": question,
        "context_history": context_history,
    })


def render_compare(pl: PromptLoader, *, agent_name: str, question: str,
                   others_answers: str) -> str:
    return pl.render("compare", {
        "agent_name": agent_name,
        "question": question,
        "others_answers": others_answers,
    })


def render_opening(pl: PromptLoader, *, moderator_name: str, topic: str,
                   guests_list: str, guests_action_format: str) -> str:
    return pl.render("opening", {
        "moderator_name": moderator_name,
        "topic": topic,
        "guests_list": guests_list,
        "guests_action_format": guests_action_format,
    })


def render_guest(pl: PromptLoader, *, agent_name: str, context: str,
                 round_num: int, moderator_question: str, action_type: str,
                 action_instruction: str, prior_speeches: str) -> str:
    return pl.render("guest", {
        "agent_name": agent_name,
        "context": context,
        "round_num": str(round_num),
        "moderator_question": moderator_question,
        "action_type": action_type,
        "action_instruction": action_instruction,
        "prior_speeches": prior_speeches,
    })


def render_moderator(pl: PromptLoader, *, moderator_name: str, context: str,
                     round_num: int, round_speeches: str, guests_list: str,
                     guests_action_format: str) -> str:
    return pl.render("moderator", {
        "moderator_name": moderator_name,
        "context": context,
        "round_num": str(round_num),
        "round_speeches": round_speeches,
        "guests_list": guests_list,
        "guests_action_format": guests_action_format,
    })


def render_solo(pl: PromptLoader, *, topic: str, context: str,
                round_num: int, moderator_question: str) -> str:
    return pl.render("solo_roundtable", {
        "topic": topic,
        "context": context,
        "round_num": str(round_num),
        "moderator_question": moderator_question,
    })


def render_compress(pl: PromptLoader, *, round_content: str) -> str:
    return pl.render("compress", {"round_content": round_content})
