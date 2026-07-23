from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

SYSTEM_PROMPT_FILES = (
    "system.md",
    "principles.md",
    "interview.md",
    "risk_matrix.md",
    "communication.md",
)


def load_prompt_file(filename: str) -> str:
    """Загружает один файл с инструкциями для LLM."""
    path = PROMPTS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Не найден файл промпта: {path}"
        )

    return path.read_text(encoding="utf-8").strip()


def build_system_prompt() -> str:
    """Объединяет правила консультанта в один системный промпт."""
    sections = [
        load_prompt_file(filename)
        for filename in SYSTEM_PROMPT_FILES
    ]

    return "\n\n---\n\n".join(sections)