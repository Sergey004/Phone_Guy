import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ai_core.ai_config import DEFAULT_PROMPT


class TestAIPrompt:
    """Tests for AI configuration prompt"""

    def test_default_prompt_is_not_empty(self):
        """Test that DEFAULT_PROMPT contains content"""
        assert len(DEFAULT_PROMPT) > 0

    def test_default_prompt_contains_phone_guy_reference(self):
        """Test that prompt mentions Phone Guy character"""
        assert "Phone Guy" in DEFAULT_PROMPT

    def test_default_prompt_contains_emotion_tags(self):
        """Test that prompt includes supported emotion tags"""
        expected_tags = [
            "[clear throat]",
            "[sigh]",
            "[chuckle]",
            "[laugh]",
        ]
        for tag in expected_tags:
            assert tag in DEFAULT_PROMPT, f"Missing tag: {tag}"

    def test_default_prompt_warns_against_asterisks(self):
        """Test that prompt warns against asterisk usage for emotions"""
        # Prompt should warn about NOT using asterisks for emotions
        assert "asterisks" in DEFAULT_PROMPT.lower() or "asterisk" in DEFAULT_PROMPT.lower()

    def test_default_prompt_enforces_english(self):
        """Test that prompt specifies English language only"""
        assert "ENGLISH" in DEFAULT_PROMPT or "english" in DEFAULT_PROMPT

    def test_default_prompt_enforces_conciseness(self):
        """Test that prompt mentions keeping responses concise"""
        assert "concise" in DEFAULT_PROMPT.lower() or "short" in DEFAULT_PROMPT.lower()
