"""内置 Skill 包加载器 —— 扫描 skills/ 目录，解析 SKILL.md（Claude 格式）

skills/ 目录（默认 ./skills，可用 SKILLS_DIR 环境变量覆盖）：
  - 每个 `.md` 文件 = 一个技能（支持 <skill名>/SKILL.md 目录结构）
  - 文件顶部 `--- frontmatter ---` 包含 name / description
  - README.md 不会被当作技能

改 skill 文件后需重启服务生效（启动时加载并缓存）。
"""

import re
from pathlib import Path

import yaml

from app.core.config import get_settings

settings = get_settings()
_skills_cache: list | None = None


def _extract_triggers(description: str) -> list[str]:
    """从技能描述中提取引号包裹的触发词（支持 「...」 "...' 等），并按 / 、 | 等分隔符拆分"""
    if not description:
        return []
    triggers = []
    for quoted in re.findall(r"[「『\"']([^」』\"']+)[」』\"']", description):
        for part in re.split(r"[、/|，,;；]", quoted):
            part = part.strip()
            if part:
                triggers.append(part)
    return triggers


def _parse_modes(meta: dict) -> list[str]:
    """解析可选 mode 字段：learning / query / all（空列表 = 所有模式都可用）"""
    raw = meta.get("mode")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(m).strip().lower() for m in raw if str(m).strip()]
    val = str(raw).strip().lower()
    if val in ("all", "both", "any"):
        return []
    return [val] if val else []


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 --- frontmatter，返回 (metadata, body)。无 frontmatter 时 metadata 为空。"""
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1])
            except Exception:
                meta = None
            if not isinstance(meta, dict):
                meta = {}
            return meta, parts[2].strip()
    return {}, text.strip()


def load_skills() -> list[dict]:
    """递归扫描 skills/ 下所有 .md，返回 [{name, description, instruction}]"""
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache
    skills = []
    skills_dir = Path(settings.skills_dir)
    if skills_dir.is_dir():
        for md in skills_dir.rglob("*.md"):
            if md.name == "README.md":
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except Exception:
                continue
            meta, body = _parse_frontmatter(text)
            # 只有带 frontmatter（含 name）的 .md 才是一个技能；
            # references/ 等纯参考文件没有 frontmatter，自动跳过，不会被误当技能
            name = meta.get("name")
            if not name or not body.strip():
                continue
            description = str(meta.get("description") or "").strip()
            skills.append({
                "name": str(name).strip(),
                "description": description,
                "instruction": body,
                "triggers": _extract_triggers(description),
                "modes": _parse_modes(meta),
            })
    _skills_cache = skills
    print(f"[Skills] 已加载 {len(skills)} 个技能: "
          + ", ".join(s["name"] for s in skills), flush=True)
    return skills


def match_skill_by_trigger(question: str, skills: list[dict], mode: str = "query") -> str | None:
    """确定性兜底：问题里出现技能描述中「...」标注的触发词时，判定该技能被使用。

    仅用于 AI 忘了输出 <!--skill:xxx--> 标记的情况（如 learning 模式）。
    skill 自己声明在 description 引号里的触发词（含「怎么理解」「教我」这类学习动词）
    都应生效——所以这里不做通用词过滤，真正的守门是下方的模式门控：
    技能声明了 mode 且不含当前模式 → 跳过（比如 learning-feynman 只在 learning 模式触发）。
    """
    for s in skills:
        if s.get("modes") and mode not in s["modes"]:
            continue
        for t in s.get("triggers", []):
            t = t.strip()
            if not t or len(t) < 2:
                continue
            if t in question:
                return s["name"]
    return None


def get_learning_skill() -> str | None:
    """返回学习模式强制使用的主学习技能名。

    优先返回配置指定的 learning_skill（默认「费曼学习计划」）；
    未加载到时回退到第一个声明了 mode: learning 的技能。
    学习模式下该技能被强制使用：生成时强制注入、识别时强制标记。
    """
    skills = load_skills()
    if settings.learning_skill:
        for s in skills:
            if s["name"] == settings.learning_skill:
                return s["name"]
    for s in skills:
        if "learning" in s.get("modes", []):
            return s["name"]
    return None


def reset_cache():
    """清空缓存（测试用）"""
    global _skills_cache
    _skills_cache = None
