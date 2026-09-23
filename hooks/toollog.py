#!/usr/bin/env python3
"""tool-log-prune: shared module and CLI.

Archive large tool results in full (SQLite, keyed by tool call id) and hand the
model only the head and tail plus a footer that says how to fetch the rest.

Imported by claude_hook.py and codex_hook.py. Called as a subprocess by
opencode_plugin.ts. Also the recall CLI the agent invokes:

  recall <id>                 full archived text        (recall = python3 toollog.py recall, installed by install.py)
  recall <id> --chunk 3/10    chunk 3 of the text split into 10 equal parts
  recall <id> --chunk 1-3/10  chunks 1 to 3 of 10
  python3 toollog.py prune-text --id ID --tool T [--session S]   stdin text -> stdout pruned (used by OpenCode)

Configuration (environment of the process that started the agent):
  TOOL_LOG_PRUNE=1     enable; anything else = pass-through
  TOOL_LOG_HEAD=500    tokens kept from the start
  TOOL_LOG_TAIL=500    tokens kept from the end
A result is pruned when it is longer than head + tail. Tokens are estimated as characters / 4.
"""
import json
import os
import shutil
import sqlite3
import sys
import time

CHARS_PER_TOKEN = 4
SELF_PATH = os.path.abspath(__file__)
DB_PATH = os.path.expanduser("~/.claude/tool-logs/tool_log.sqlite")
LOG_DIR = os.path.dirname(DB_PATH)


def _int_from_env(variable_name, default_value):
    try:
        return int(os.environ.get(variable_name, default_value))
    except ValueError:
        return default_value


HEAD_TOKENS = _int_from_env("TOOL_LOG_HEAD", 500)
TAIL_TOKENS = _int_from_env("TOOL_LOG_TAIL", 500)


def enabled():
    return os.environ.get("TOOL_LOG_PRUNE") == "1"


def log_error(source, error):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "errors.log"), "a") as error_log:
        error_log.write(f"{time.strftime('%F %T')} {source} {type(error).__name__}: {error}\n")


# ---------------------------------------------------------------- text payload in / out
#
# Known tool_response shapes:
#   plain string                      Codex shell
#   {"stdout", "stderr", ...}         Claude Code Bash
#   {"type": "text", "text"}          generic
#   {"file": {"content", ...}}        Claude Code Read
#   {"content": [...blocks]}          MCP result object
#   [{"type": "text", "text"}, ...]   Claude Code MCP tools

def _text_field(tool_response):
    """Which key of a dict tool_response holds the text, or None when it is nested."""
    if isinstance(tool_response.get("stdout"), str):
        return "stdout"
    if isinstance(tool_response.get("text"), str):
        return "text"
    if isinstance(tool_response.get("output"), str):
        return "output"
    return None


def extract_text(tool_response):
    """Text payload of a tool_response, whatever its shape."""
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, list):
        return "\n".join(extract_text(block) for block in tool_response)
    return _extract_from_dict(tool_response)


def _extract_from_dict(tool_response):
    field = _text_field(tool_response)
    if field == "stdout":
        stderr_text = tool_response.get("stderr") or ""
        return tool_response["stdout"] + (("\n[stderr]\n" + stderr_text) if stderr_text else "")
    if field:
        return tool_response[field]
    file_info = tool_response.get("file")
    if isinstance(file_info, dict) and isinstance(file_info.get("content"), str):
        return file_info["content"]
    if "content" in tool_response:
        return extract_text(tool_response["content"])
    # Unknown shape (e.g. Edit's {filePath, oldString, newString, originalFile, structuredPatch}):
    # the model sees a short rendered message, not this object, so there is nothing to replace.
    return ""


def rebuild(tool_response, replacement_text):
    """Copy of tool_response with its text payload replaced, shape preserved.

    Claude Code rejects an updatedToolOutput whose shape differs from the original.
    """
    if isinstance(tool_response, list):
        return _rebuild_blocks(tool_response, replacement_text)
    if isinstance(tool_response, dict):
        return _rebuild_dict(tool_response, replacement_text)
    return replacement_text


def _rebuild_dict(tool_response, replacement_text):
    rebuilt = dict(tool_response)
    field = _text_field(tool_response)
    if field:
        rebuilt[field] = replacement_text
        if field == "stdout" and tool_response.get("stderr"):
            rebuilt["stderr"] = "[stderr archived together with stdout, see tool-log footer]"
        return rebuilt
    file_info = tool_response.get("file")
    if isinstance(file_info, dict) and isinstance(file_info.get("content"), str):
        rebuilt["file"] = {**file_info, "content": replacement_text}
    elif "content" in tool_response:
        rebuilt["content"] = rebuild(tool_response["content"], replacement_text)
    return rebuilt


def _rebuild_blocks(blocks, replacement_text):
    """Keep non-text blocks (images), collapse all text blocks into one carrying the replacement."""
    non_text_blocks = [block for block in blocks if not (isinstance(block, dict) and block.get("type") == "text")]
    return [{"type": "text", "text": replacement_text}] + non_text_blocks


# ---------------------------------------------------------------- archive

def _connect():
    os.makedirs(LOG_DIR, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS results ("
        " id TEXT PRIMARY KEY, session_id TEXT, ts REAL, tool_name TEXT,"
        " tool_input TEXT, size_chars INTEGER, output TEXT)"
    )
    return connection


def store(tool_use_id, session_id, tool_name, tool_input, full_text):
    connection = _connect()
    tool_input_json = json.dumps(tool_input, ensure_ascii=False)[:4000] if tool_input is not None else ""
    connection.execute(
        "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?)",
        (tool_use_id, session_id or "", time.time(), tool_name, tool_input_json, len(full_text), full_text),
    )
    connection.commit()
    connection.close()


def fetch(tool_use_id):
    """Archived text for an id, or an id prefix. None if unknown."""
    connection = _connect()
    archived_row = connection.execute("SELECT output FROM results WHERE id=?", (tool_use_id,)).fetchone() \
        or connection.execute("SELECT output FROM results WHERE id LIKE ?", (tool_use_id + "%",)).fetchone()
    connection.close()
    return archived_row[0] if archived_row else None


# ---------------------------------------------------------------- pruning

RECALL_MARKER = "[tool-log "  # first line of every recall output; recall is never pruned again


def prune_limit_chars():
    return (HEAD_TOKENS + TAIL_TOKENS) * CHARS_PER_TOKEN


def needs_pruning(full_text):
    """Longer than head + tail, and not the output of a recall (the agent asked for that text on purpose)."""
    if full_text.lstrip().startswith(RECALL_MARKER):
        return False
    return len(full_text) > prune_limit_chars()


def recall_command(tool_use_id):
    """`recall <id>` when install.py put the shim on PATH, otherwise the full path to this file."""
    if shutil.which("recall"):
        return f"recall {tool_use_id}"
    return f"python3 {SELF_PATH} recall {tool_use_id}"


def footer(tool_use_id, size_chars):
    estimated_tokens = size_chars // CHARS_PER_TOKEN
    command = recall_command(tool_use_id)
    chunks_under_limit = -(-size_chars // prune_limit_chars())  # ceil: N so that one chunk fits in head + tail
    return (
        f"\n\n[tool-log: output truncated. {size_chars:,} chars (~{estimated_tokens:,} tokens) archived under id {tool_use_id};"
        f" shown above: first {HEAD_TOKENS} and last {TAIL_TOKENS} tokens. The middle is NOT lost. Retrieve it with:"
        f"\n  {command} --chunk K/N      chunk K of the full text split into N equal parts (e.g. --chunk 1/{chunks_under_limit}, each chunk about {HEAD_TOKENS + TAIL_TOKENS} tokens)"
        f"\n  {command} --chunk A-B/N    chunks A through B of N (e.g. --chunk 1-3/10)"
        f"\n  {command}                  everything"
        f"\nRecall output is never pruned.]"
    )


def prune(full_text, tool_use_id, session_id, tool_name, tool_input):
    """Archive full_text and return the pruned version. Caller checks needs_pruning() first."""
    store(tool_use_id, session_id, tool_name, tool_input, full_text)
    head_text = full_text[: HEAD_TOKENS * CHARS_PER_TOKEN]
    tail_text = full_text[-TAIL_TOKENS * CHARS_PER_TOKEN:]
    return head_text + "\n\n[... truncated ...]\n\n" + tail_text + footer(tool_use_id, len(full_text))


def prune_hook_event(hook_event, agent_name):
    """Shared hook flow for Claude Code and Codex.

    Returns (tool_response, pruned_text), or None when nothing should change:
    pruning disabled, or the result fits within head + tail.
    """
    if not enabled():
        return None
    tool_response = hook_event.get("tool_response")
    full_text = extract_text(tool_response)
    if not needs_pruning(full_text):
        return None
    tool_use_id = hook_event.get("tool_use_id") or f"{agent_name}-{int(time.time() * 1000)}"
    tool_name = f"{agent_name}:{hook_event.get('tool_name', '')}"
    pruned_text = prune(full_text, tool_use_id, hook_event.get("session_id", ""), tool_name, hook_event.get("tool_input"))
    return tool_response, pruned_text


def chunk_text(full_text, chunk_spec):
    """Split full_text into equal parts. chunk_spec is 'K/N' or 'A-B/N' (1-based, inclusive).

    Returns (selected_text, first_chunk, last_chunk, chunk_count, start_char, end_char).
    """
    selection, chunk_count_text = chunk_spec.split("/")
    chunk_count = int(chunk_count_text)
    bounds = selection.split("-")
    first_chunk = int(bounds[0])
    last_chunk = int(bounds[1]) if len(bounds) > 1 and bounds[1] else first_chunk
    if chunk_count < 1 or first_chunk < 1 or last_chunk < first_chunk or last_chunk > chunk_count:
        raise ValueError(f"bad chunk spec {chunk_spec}: use K/N or A-B/N with 1 <= A <= B <= N")
    chunk_size = -(-len(full_text) // chunk_count)  # ceiling division
    start_char = (first_chunk - 1) * chunk_size
    end_char = min(last_chunk * chunk_size, len(full_text))
    return full_text[start_char:end_char], first_chunk, last_chunk, chunk_count, start_char, end_char


# ---------------------------------------------------------------- CLI

def _command_prune_text(arguments):
    options = dict(zip(arguments[::2], arguments[1::2]))
    full_text = sys.stdin.read()
    if not enabled() or not needs_pruning(full_text):
        return 0  # empty stdout = leave unchanged
    tool_use_id = options.get("--id", f"unknown-{int(time.time() * 1000)}")
    sys.stdout.write(prune(full_text, tool_use_id, options.get("--session", ""), options.get("--tool", ""), None))
    return 0


def _command_recall(arguments):
    if not arguments:
        print("usage: recall <id> [--chunk K/N | --chunk A-B/N]", file=sys.stderr)
        return 2
    tool_use_id, options = arguments[0], arguments[1:]
    full_text = fetch(tool_use_id)
    if full_text is None:
        print(f"no archived result for id {tool_use_id}", file=sys.stderr)
        return 1
    if options[:1] != ["--chunk"]:
        sys.stdout.write(f"[tool-log {tool_use_id}: full text, {len(full_text):,} chars]\n{full_text}\n")
        return 0
    try:
        selected_text, first_chunk, last_chunk, chunk_count, start_char, end_char = chunk_text(full_text, options[1])
    except (ValueError, IndexError) as error:
        print(error or "usage: recall <id> --chunk K/N", file=sys.stderr)
        return 2
    label = f"chunk {first_chunk}/{chunk_count}" if first_chunk == last_chunk else f"chunks {first_chunk}-{last_chunk}/{chunk_count}"
    sys.stdout.write(f"[tool-log {tool_use_id}: {label}, chars {start_char:,}..{end_char:,} of {len(full_text):,}]\n{selected_text}\n")
    return 0


COMMANDS = {"prune-text": _command_prune_text, "recall": _command_recall}


def cli(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
