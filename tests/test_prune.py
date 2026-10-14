import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hooks'))
import prune
import toollog

class HookTests(unittest.TestCase):
    def invoke(self, event):
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(event))), contextlib.redirect_stdout(output):
            prune.main()
        return output.getvalue()

    def test_legacy_codex_does_not_stop_or_archive(self):
        with patch.object(toollog, 'prune_hook_event') as handler:
            self.assertEqual(self.invoke({'turn_id':'test', 'tool_response':'x'*12000}), '')
            handler.assert_not_called()

    def test_claude_prunes_and_preserves_full_archive(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'TOOL_LOG_PRUNE':'1'}), \
             patch.object(toollog, 'LOG_DIR', tmp), patch.object(toollog, 'DB_PATH', str(Path(tmp)/'archive.sqlite')):
            original = 'a'*12000
            response = json.loads(self.invoke({'tool_use_id':'test', 'tool_name':'Bash',
                'tool_response':{'stdout':original, 'exitCode':0}}))
            updated = response['hookSpecificOutput']['updatedToolOutput']
            self.assertLess(len(updated['stdout']), len(original))
            self.assertIn('recall', updated['stdout'])
            self.assertEqual(updated['exitCode'], 0)
            self.assertEqual(toollog.fetch('test'), original)
            self.assertNotIn('continue', response)

if __name__ == '__main__':
    unittest.main()
