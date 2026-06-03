"""LLM 模型选择规则。"""
from app.config import settings
from app.models import Project


def resolve_project_model(project: Project | None, requested_model: str | None = None) -> str:
    requested = (requested_model or "").strip()
    if requested:
        return requested
    if project is not None and isinstance(project.style_guide, dict):
        project_model = project.style_guide.get("model")
        if isinstance(project_model, str) and project_model.strip():
            return project_model.strip()
    return settings.claude_model