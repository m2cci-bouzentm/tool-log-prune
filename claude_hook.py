#!/usr/bin/env python3
"""Claude Code PostToolUse hook: stdin hook event -> stdout hookSpecificOutput.updatedToolOutput.

Claude Code rejects an updatedToolOutput whose shape differs from the original tool_response,
so the pruned text is placed back inside a copy of the original structure.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toollog  # noqa: E402


def main():
    result = toollog.prune_hook_event(json.load(sys.stdin), "claude")
    if result is None:
        return
    tool_response, pruned_text = result
    updated_output = toollog.rebuild(tool_response, pruned_text)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated_output}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # never break the tool call; leave output intact
        toollog.log_error("claude_hook", error)
