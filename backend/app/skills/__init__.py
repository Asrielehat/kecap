"""技能（Skill）系统 —— 加载、匹配、注入提示词

技能文件格式：skills/<技能名>/SKILL.md 或 skills/<技能名>.md，
frontmatter（yaml）定义 name/description/mode/force/triggers/needs_full_history，
正文为注入 LLM 的指令。采用 SKILL.md 的通用规范布局。
"""

from app.skills.loader import Skill, load_skills, list_skills, resolve_skill

__all__ = ["Skill", "load_skills", "list_skills", "resolve_skill"]
