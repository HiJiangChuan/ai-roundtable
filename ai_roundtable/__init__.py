"""AI Roundtable — 多个 AI CLI 同台讨论的终端应用。"""
import re
from importlib import metadata as _metadata
from pathlib import Path

__all__ = ["__version__"]


def _read_version() -> str:
    """版本号单一来源是 pyproject.toml。

    源码运行时直接读仓库里的 pyproject（比 editable 安装的元数据更新）；
    安装后从包元数据读取。
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"',
                      pyproject.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    try:
        return _metadata.version("ai-roundtable")
    except _metadata.PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = _read_version()
