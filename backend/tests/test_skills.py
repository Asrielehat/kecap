"""技能系统测试 —— unittest（零新依赖，无需 pytest）

覆盖：
- resolve_skill 三态：触发词命中 / 未命中 / mode 强制门控
- 坏文件跳过、目录不存在静默降级
- generate_answer 技能注入 + 全历史（mock LLM 捕获 messages）
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.core.config import get_settings
from app.skills import loader as skill_loader

settings = get_settings()

# ── 测试用技能内容 ──
LEARNING_SUMMARY_MD = """---
name: learning_summary
description: 学习总结
mode: all
force: false
triggers:
  - 帮我总结
  - 学到了什么
  - 总结一下
needs_full_history: true
---

你是学习总结专家，输出 Mermaid mindmap。"""

FORCED_SKILL_MD = """---
name: forced_skill
description: 学习模式强制技能
mode: learning
force: true
triggers: []
---

学习模式必触发技能指令。"""

BAD_SKILL_MD = "## 没有 frontmatter 的文件，应该被跳过"


class TestSkillLoader(unittest.TestCase):
    """技能加载与匹配（纯函数）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._skills_root = Path(self._tmp.name)
        self._old_enabled = settings.skills_enabled
        self._old_dir = settings.skills_dir
        settings.skills_enabled = True
        settings.skills_dir = str(self._skills_root)
        skill_loader.load_skills.cache_clear()

    def tearDown(self):
        settings.skills_enabled = self._old_enabled
        settings.skills_dir = self._old_dir
        skill_loader.load_skills.cache_clear()
        self._tmp.cleanup()

    def _write(self, rel: str, content: str):
        p = self._skills_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def test_trigger_match(self):
        self._write("learning_summary/SKILL.md", LEARNING_SUMMARY_MD)
        skill = skill_loader.resolve_skill("帮我总结我学到了什么", "all")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "learning_summary")

    def test_no_match(self):
        self._write("learning_summary/SKILL.md", LEARNING_SUMMARY_MD)
        self.assertIsNone(skill_loader.resolve_skill("什么是二叉树", "all"))

    def test_mode_force(self):
        self._write("forced_skill.md", FORCED_SKILL_MD)
        skill = skill_loader.resolve_skill("随便问什么", "learning")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "forced_skill")
        # all 模式不触发（mode 门控）
        self.assertIsNone(skill_loader.resolve_skill("随便问什么", "all"))

    def test_bad_file_skipped(self):
        self._write("bad.md", BAD_SKILL_MD)
        self.assertEqual(skill_loader.load_skills(), [])

    def test_missing_dir(self):
        settings.skills_dir = str(self._skills_root / "nope")
        skill_loader.load_skills.cache_clear()
        self.assertEqual(skill_loader.load_skills(), [])


class TestGeneratorSkillInjection(unittest.TestCase):
    """generate_answer 技能注入 + 全历史（mock LLM 捕获 messages）"""

    def setUp(self):
        import app.rag.generator as gen
        self.gen = gen
        self._tmp = tempfile.TemporaryDirectory()
        self._skills_root = Path(self._tmp.name)
        self._old_enabled = settings.skills_enabled
        self._old_dir = settings.skills_dir
        settings.skills_enabled = True
        settings.skills_dir = str(self._skills_root)
        skill_loader.load_skills.cache_clear()
        p = self._skills_root / "learning_summary" / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(LEARNING_SUMMARY_MD, encoding="utf-8")

    def tearDown(self):
        settings.skills_enabled = self._old_enabled
        settings.skills_dir = self._old_dir
        skill_loader.load_skills.cache_clear()
        self._tmp.cleanup()

    def _patch_create(self, captured: dict):
        def fake_create(model, messages, temperature, max_tokens, **kw):
            captured["messages"] = messages
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="总结好了"))])
        return mock.patch.object(self.gen.llm_client.chat.completions, "create", side_effect=fake_create)

    def test_summary_skill_full_history_injection(self):
        captured = {}
        with self._patch_create(captured):
            history = []
            for i in range(6):   # 12 条消息 > 10 条截断线
                history.append({"role": "user", "content": f"问题{i}"})
                history.append({"role": "assistant", "content": f"回答{i}"})
            result = self.gen.generate_answer("帮我总结我学到了什么", [], history, mode="all")

        msgs = captured["messages"]
        # index=1 是技能指令 system 消息（插在 SYSTEM_PROMPT 之后）
        self.assertEqual(msgs[1]["role"], "system")
        self.assertIn("mindmap", msgs[1]["content"])
        # 全历史注入：第一条问题（问题0）仍在，未被 [-10:] 截断
        self.assertTrue(any("问题0" in m["content"] for m in msgs if m["role"] == "user"))
        # 结果正常返回
        self.assertEqual(result["answer"], "总结好了")

    def test_normal_question_no_skill(self):
        captured = {}
        with self._patch_create(captured):
            history = [{"role": "user", "content": f"问题{i}"} for i in range(12)]
            self.gen.generate_answer("什么是二叉树", [], history, mode="all")

        msgs = captured["messages"]
        # 无技能注入：index=1 是第一条历史（user），不是技能指令
        self.assertNotIn("mindmap", msgs[1]["content"])
        self.assertEqual(msgs[1]["role"], "user")


if __name__ == "__main__":
    unittest.main()
