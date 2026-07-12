"""主持人输出解析。"""
import re
from typing import Dict, Optional

SECTIONS = ("矛盾点", "下一问", "行动分配", "本轮摘要")
ESSENTIAL = ("矛盾点", "下一问")


def parse_moderator_output(text: str) -> Optional[Dict[str, str]]:
    """把主持人的【段落】格式解析为 dict。

    只强制要求「矛盾点」和「下一问」两个核心段落——
    行动分配缺失时下游会用默认分配，本轮摘要缺失时压缩走 compress prompt。
    """
    result: Dict[str, str] = {}
    for section in SECTIONS:
        m = re.search(r"【" + section + r"】\s*(.*?)(?=【|$)", text, re.DOTALL)
        if m:
            value = m.group(1).strip()
            if value:
                result[section] = value
    if not all(key in result for key in ESSENTIAL):
        return None
    return result


def parse_action_assignments(action_text: str) -> Dict[str, Dict[str, str]]:
    """解析行动分配文本 → {agent: {type, instruction}}。

    容忍常见的 LLM 格式噪音：列表符号、markdown 加粗、全/半角冒号与各种破折号。
    """
    assignments: Dict[str, Dict[str, str]] = {}
    for line in action_text.strip().split("\n"):
        line = line.strip().lstrip("-*•").strip()
        line = line.replace("**", "")
        m = re.match(r"^(\w+)[：:]\s*([^-–—]+?)\s*[-–—]\s*(.+)$", line)
        if m:
            assignments[m.group(1).lower()] = {
                "type": m.group(2).strip(),
                "instruction": m.group(3).strip(),
            }
    return assignments
