#!/usr/bin/env python3
"""Claude Code PostToolUse hook: archive and replace large tool output.

Legacy Codex invocations are ignored before archiving. Returning continue=false
stops current Codex runs and is not a supported pruning mechanism.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toollog  # noqa: E402


def main():
    hook_event = json.load(sys.stdin)
    if "turn_id" in hook_event:
        return  # Old Codex registrations must neither stop nor archive.
    result = toollog.prune_hook_event(hook_event, "claude")
    if result is None:
        return
    tool_response, pruned_text = result
    updated_output = toollog.rebuild(tool_response, pruned_text)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated_output}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # never break the tool call; leave output intact
        toollog.log_error("prune_hook", error)
