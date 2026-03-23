"""
Prompt Loader - Loads and renders prompt templates with variable substitution.
"""
import re
from pathlib import Path
from typing import Dict, List


REQUIRED_PROMPTS = ["opening", "guest", "guest_quick", "moderator", "compare"]


class PromptLoader:
    def __init__(self, prompts_dir: Path):
        self.prompts_dir = Path(prompts_dir)
        self._cache: Dict[str, str] = {}

    def _load(self, template_name: str) -> str:
        """Load a template file, using cache."""
        if template_name not in self._cache:
            path = self.prompts_dir / f"{template_name}.md"
            if not path.exists():
                raise FileNotFoundError(f"Prompt template not found: {path}")
            self._cache[template_name] = path.read_text(encoding='utf-8')
        return self._cache[template_name]

    def render(self, template_name: str, variables: Dict[str, str]) -> str:
        """
        Load template and replace {{variable}} placeholders with values.
        Unknown variables are left as-is.
        """
        template = self._load(template_name)
        result = template

        for key, value in variables.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, str(value) if value is not None else "")

        return result

    def check_all(self) -> List[str]:
        """
        Check if all required prompt files exist.
        Returns list of missing file names (without extension).
        """
        missing = []
        for name in REQUIRED_PROMPTS:
            path = self.prompts_dir / f"{name}.md"
            if not path.exists():
                missing.append(name)
        return missing
