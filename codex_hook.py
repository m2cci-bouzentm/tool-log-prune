#!/usr/bin/env python3
"""Codex PostToolUse hook: stdin hook event -> stdout {"continue": false, "reason": <pruned>}.

Codex uses the reason as the model-visible tool result; the original stays in its logs and UI.
This applies only on the direct function-tool path: models catalogued as code_mode_only run the
hook (the result is archived) but keep the original output by design.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toollog  # noqa: E402


def main():
    result = toollog.prune_hook_event(json.load(sys.stdin), "codex")
    if result is None:
        return
    _, pruned_text = result
    print(json.dumps({"continue": False, "stopReason": "tool output pruned", "reason": pruned_text}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        toollog.log_error("codex_hook", error)
