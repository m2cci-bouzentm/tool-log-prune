#!/usr/bin/env python3
"""PostToolUse hook: archive large tool results, keep head + tail in context.

Every tool result above THRESHOLD_TOKENS is stored in full in a SQLite database
keyed by tool_use_id. What reaches the model is the first HEAD_TOKENS and the
last TAIL_TOKENS of the output plus a footer that names the id and the recall
command. Small results pass through untouched. The replacement happens before
the result enters the context, so the prompt-cache prefix stays append-only.

Recall the full text later with:  python3 ~/.claude/hooks/tool-log/recall.py <id>
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

# Tools whose output the model asked for verbatim; truncating them only causes a re-read.
SKIP_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}


def extract_text(resp):
    """tool_response can be a string, {text}, {content:[{type:text,text}]} or a list of blocks."""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "\n".join(extract_text(b) for b in resp)
    if isinstance(resp, dict):
        if isinstance(resp.get("text"), str):
            return resp["text"]
        if isinstance(resp.get("stdout"), str):  # Bash: {stdout, stderr, interrupted, ...}
            err = resp.get("stderr") or ""
            return resp["stdout"] + (("\n[stderr]\n" + err) if err else "")
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
        (tool_use_id, session_id, time.time(), tool_name,
         json.dumps(tool_input, ensure_ascii=False)[:4000], len(text), text),
    )
    con.commit()
    con.close()


def main():
    # Opt-in only: the wrapper command sets TOOL_LOG_PRUNE=1 before starting the agent.
    if os.environ.get("TOOL_LOG_PRUNE") != "1":
        return
    try:
        event = json.load(sys.stdin)
    except Exception:
        return
    tool_name = event.get("tool_name", "")
    if tool_name in SKIP_TOOLS:
        return
    text = extract_text(event.get("tool_response"))
    if len(text) <= THRESHOLD_TOKENS * CHARS_PER_TOKEN:
        return

    tool_use_id = event.get("tool_use_id") or f"unknown-{int(time.time() * 1000)}"
    if os.environ.get("TOOL_LOG_DEBUG") == "1":
        with open(os.path.expanduser("~/.claude/tool-logs/last_event.json"), "w") as fh:
            json.dump(event, fh)
    try:
        store(tool_use_id, event.get("session_id", ""), tool_name, event.get("tool_input"), text)
    except Exception as exc:
        # Never lose the result: if the archive fails, leave the output untouched.
        sys.stderr.write(f"tool-log: store failed, output left intact: {exc}\n")
        return

    head = text[: HEAD_TOKENS * CHARS_PER_TOKEN]
    tail = text[-TAIL_TOKENS * CHARS_PER_TOKEN:]
    footer = (
        f"\n\n[tool-log: {len(text):,} chars archived, showing first {HEAD_TOKENS} and last {TAIL_TOKENS} tokens."
        f" id={tool_use_id}."
        f" Full text: python3 ~/.claude/hooks/tool-log/recall.py {tool_use_id} [--grep PATTERN]]"
    )
    replaced = head + "\n\n[... truncated ...]\n\n" + tail + footer

    # Claude Code validates that updatedToolOutput has the same shape as the original
    # tool_response ("does not match output shape; using original output"), so rebuild
    # the original structure with only the text payload swapped.
    updated = rebuild(event.get("tool_response"), replaced)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated}}))


def rebuild(resp, replaced):
    """Return a copy of resp with its text payload replaced by `replaced`, shape preserved."""
    if isinstance(resp, str):
        return replaced
    if isinstance(resp, dict):
        out = dict(resp)
        if isinstance(resp.get("stdout"), str):  # Bash
            out["stdout"] = replaced
            if resp.get("stderr"):
                out["stderr"] = "[stderr archived with the stdout, see tool-log footer]"
            return out
        if isinstance(resp.get("text"), str):
            out["text"] = replaced
            return out
        if "content" in resp:
            out["content"] = rebuild(resp["content"], replaced)
            return out
        if isinstance(resp.get("output"), str):
            out["output"] = replaced
            return out
        return out
    if isinstance(resp, list):
        # Content blocks: keep non-text blocks, collapse text blocks into the first one.
        out = []
        placed = False
        for b in resp:
            if isinstance(b, dict) and b.get("type") == "text":
                if not placed:
                    out.append({**b, "text": replaced})
                    placed = True
            else:
                out.append(b)
        if not placed:
            out.insert(0, {"type": "text", "text": replaced})
        return out
    return replaced


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break the tool call; log and leave output intact
        try:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            with open(os.path.join(os.path.dirname(DB_PATH), "errors.log"), "a") as fh:
                fh.write(f"{time.strftime('%F %T')} {type(exc).__name__}: {exc}\n")
        except Exception:
            pass
