#!/usr/bin/env python3
"""PostToolUse hook for Claude Code and Codex: stdin hook event -> stdout replacement.

Both hosts send the same event fields (tool_name, tool_input, tool_response, tool_use_id,
session_id); Codex additionally sends turn_id. The reply differs:

  Claude Code  {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <same shape as tool_response>}}
  Codex        {"continue": false, "reason": <pruned text>}   (model-visible result; original stays in Codex logs)

Codex applies the replacement only on the direct function-tool path: code_mode_only models run
the hook (the result is archived) but keep the original output by design.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toollog  # noqa: E402


def main():
    hook_event = json.load(sys.stdin)
    host = "codex" if "turn_id" in hook_event else "claude"
    result = toollog.prune_hook_event(hook_event, host)
    if result is None:
        return
    tool_response, pruned_text = result
    if host == "codex":
        print(json.dumps({"continue": False, "stopReason": "tool output pruned", "reason": pruned_text}))
        return
    updated_output = toollog.rebuild(tool_response, pruned_text)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated_output}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # never break the tool call; leave output intact
        toollog.log_error("prune_hook", error)
