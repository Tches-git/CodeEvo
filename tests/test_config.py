import os
import tempfile
import unittest
from unittest.mock import patch

from codeevo.config import Settings, load_dotenv


class DotenvTests(unittest.TestCase):
    def test_loads_valid_assignments_and_quoted_values(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("# comment\n")
            handle.write("export CODEEVO_LLM_PROVIDER=deepseek\n")
            handle.write('CODEEVO_DEEPSEEK_API_KEY="test-key"\n')
            handle.write("invalid line\n")
            path = handle.name
        try:
            with patch.dict(os.environ, {}, clear=True):
                load_dotenv([path])
                self.assertEqual("deepseek", os.environ["CODEEVO_LLM_PROVIDER"])
                self.assertEqual("test-key", os.environ["CODEEVO_DEEPSEEK_API_KEY"])
        finally:
            os.unlink(path)

    def test_process_environment_has_priority(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("CODEEVO_LLM_PROVIDER=deepseek\n")
            path = handle.name
        try:
            with patch.dict(os.environ, {"CODEEVO_LLM_PROVIDER": "custom"}, clear=True):
                load_dotenv([path])
                self.assertEqual("custom", os.environ["CODEEVO_LLM_PROVIDER"])
        finally:
            os.unlink(path)

    def test_llm_price_snapshot_requires_both_input_and_output_prices(self):
        with patch.dict(os.environ, {
            "CODEEVO_LLM_INPUT_COST_PER_MILLION": "1.0",
            "CODEEVO_LLM_OUTPUT_COST_PER_MILLION": "",
        }, clear=True):
            settings = Settings.from_env()
            with self.assertRaisesRegex(ValueError, "configured together"):
                settings.validate_evolution()
