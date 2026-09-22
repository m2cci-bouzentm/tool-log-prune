#!/usr/bin/env python3
"""Codex PostToolUse hook: archive large tool results, keep head + tail for the model.

Same policy and same SQLite archive as the Claude Code hook
(~/.claude/hooks/tool-log/prune.py). Active only when TOOL_LOG_PRUNE=1 is set in the
environment that launched codex (see ~/.claude/hooks/tool-log/lean.sh, `codex-lean`).

Codex replaces the model-visible tool result when a PostToolUse hook returns
{"continue": false, "reason": "<text>"}; the original stays in logs and the UI.
"""
import json
import os
import sqlite3
import sys
import time

THRESHOLD_TOKENS = 1000
HEAD_TOKENS = 500
TAIL_TOKENS = 500
CHARS_PER_TOKEN = 4
DB_PATH = os.path.expanduser("~/.claude/tool-logs/tool_log.sqlite")


def extract_text(resp):
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "\n".join(extract_text(b) for b in resp)
    if isinstance(resp, dict):
        if isinstance(resp.get("text"), str):
            return resp["text"]
        if "content" in resp:
            return extract_text(resp["content"])
        if isinstance(resp.get("output"), str):
            return resp["output"]
        return json.dumps(resp, ensure_ascii=False)
    return str(resp)


def store(tool_use_id, session_id, tool_name, tool_input, text):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS results ("
        " id TEXT PRIMARY KEY, session_id TEXT, ts REAL, tool_name TEXT,"
        " tool_input TEXT, size_chars INTEGER, output TEXT)"
    )
    con.execute(
        "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?)",
        (tool_use_id, session_id, time.time(), "codex:" + tool_name,
         json.dumps(tool_input, ensure_ascii=False)[:4000], len(text), text),
    )
    con.commit()
    con.close()


def main():
    if os.environ.get("TOOL_LOG_PRUNE") != "1":
        return
    event = json.load(sys.stdin)
    if os.environ.get("TOOL_LOG_DEBUG") == "1":
        with open(os.path.expanduser("~/.claude/tool-logs/last_codex_event.json"), "w") as fh:
            json.dump(event, fh)
    text = extract_text(event.get("tool_response"))
    if len(text) <= THRESHOLD_TOKENS * CHARS_PER_TOKEN:
        return
    tool_use_id = event.get("tool_use_id") or f"codex-{int(time.time() * 1000)}"
    store(tool_use_id, event.get("session_id", ""), event.get("tool_name", ""), event.get("tool_input"), text)
    head = text[: HEAD_TOKENS * CHARS_PER_TOKEN]
    tail = text[-TAIL_TOKENS * CHARS_PER_TOKEN:]
    footer = (
        f"\n\n[tool-log: {len(text):,} chars archived, showing first {HEAD_TOKENS} and last {TAIL_TOKENS} tokens."
        f" id={tool_use_id}."
        f" Full text: python3 ~/.claude/hooks/tool-log/recall.py {tool_use_id} [--grep PATTERN]]"
    )
    print(json.dumps({"continue": False, "stopReason": "tool output pruned", "reason": head + "\n\n[... truncated ...]\n\n" + tail + footer}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            with open(os.path.expanduser("~/.claude/tool-logs/errors.log"), "a") as fh:
                fh.write(f"{time.strftime('%F %T')} codex {type(exc).__name__}: {exc}\n")
        except Exception:
            pass
