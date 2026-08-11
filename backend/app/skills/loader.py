"""技能加载与匹配 —— 扫描 SKILLS_DIR 下的技能文件，解析 frontmatter + body，缓存到内存

选择优先级：mode 强制（force=true 且 mode 匹配）> 触发词子串命中 > 无匹配。
纯函数、无 DB，chat.py 与 generator.py 可各自调用 resolve_skill，结果必然一致。
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import get_settings

settings = get_settings()


@dataclass
class Skill:
    name: str
    description: str = ""
    mode: list[str] = field(default_factory=lambda: ["all"])  # 适用 mode（all/query/learning）
    force: bool = False            # 在适用 mode 下是否强制触发
    triggers: list[str] = field(default_factory=list)        # 触发词（子串匹配）
    needs_full_history: bool = False  # 是否需要完整对话历史
    instruction: str = ""          # 注入 LLM 的指令正文（SKILL.md body）
    source_path: str = ""          # 技能文件路径（调试用）

    def applies_to(self, mode: str) -> bool:
        return "all" in self.mode or mode in self.mode


def _load_skill_file(path: Path) -> Skill | None:
    """解析单个 SKILL.md：frontmatter（yaml） + body 指令。解析失败返回 None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[Skill] 读取技能文件失败: {path} -> {e}", flush=True)
        return None
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not fm_match:
        return None
    meta = yaml.safe_load(fm_match.group(1)) or {}
    body = fm_match.group(2).strip()
    if not body:
        return None
    mode = meta.get("mode", "all")
    if isinstance(mode, str):
        mode = [mode]
    mode = [m for m in mode if m] or ["all"]
    return Skill(
        name=meta.get("name") or path.stem,
        description=meta.get("description", ""),
        mode=mode,
        force=bool(meta.get("force", False)),
        triggers=[t for t in (meta.get("triggers") or []) if t],
        needs_full_history=bool(meta.get("needs_full_history", False)),
        instruction=body,
        source_path=str(path),
    )


@lru_cache(maxsize=1)
def load_skills() -> list[Skill]:
    """扫描 SKILLS_DIR，加载全部技能。目录不存在 / 全解析失败时返回空列表（技能系统静默降级）。"""
    skills_dir = Path(settings.skills_dir).resolve()
    if not skills_dir.is_dir():
        print(f"[Skill] 技能目录不存在，技能系统不可用: {skills_dir}", flush=True)
        return []
    skills = []
    for p in sorted(skills_dir.rglob("*.md")):   # 同时支持 <name>/SKILL.md 与 <name>.md
        skill = _load_skill_file(p)
        if skill:
            skills.append(skill)
    return skills


def list_skills() -> list[dict]:
    """列出所有可用技能（供调试/未来前端展示）"""
    return [
        {"name": s.name, "description": s.description, "mode": s.mode,
         "force": s.force, "needs_full_history": s.needs_full_history}
        for s in load_skills()
    ]


def resolve_skill(question: str, mode: str = "all") -> Skill | None:
    """技能选择：mode 强制 > 触发词子串命中 > 无匹配。纯函数、确定性、无 DB。"""
    skills = load_skills()
    if not skills:
        return None
    # 第一优先级：mode 匹配且 force=true 的必触发技能（取声明顺序第一个）
    for s in skills:
        if s.force and s.applies_to(mode):
            print(f"[Skill] mode={mode} 强制触发技能: {s.name}", flush=True)
            return s
    # 第二优先级：触发词子串命中（问题包含任一触发词）
    for s in skills:
        if s.applies_to(mode) and any(t in question for t in s.triggers):
            print(f"[Skill] 触发词命中: {s.name}", flush=True)
            return s
    return None


def get_skill_instruction(name: str) -> str | None:
    """按技能名取指令正文（显式触发预留，当前未使用）"""
    for s in load_skills():
        if s.name == name:
            return s.instruction
    return None
