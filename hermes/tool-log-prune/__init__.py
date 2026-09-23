"""Hermes Agent plugin: prune large tool results before they enter the model context.

Registers ``transform_tool_result``, the hook Hermes runs after ``post_tool_call`` and before
the result string is appended to the conversation. It fires for every tool (built-in, MCP,
plugin) and every model provider. The plugin is loaded per profile from
``$HERMES_HOME/plugins/tool-log-prune`` (install.py symlinks it into every profile) and is
switched on by ``plugins.enabled`` in that profile's config.yaml, so unlike the other hosts
there is no TOOL_LOG_PRUNE=1 to set: loaded means active. ``TOOL_LOG_PRUNE=0`` is the kill switch.

Hermes tool results are strings, usually JSON. A JSON object with a known text field
(terminal ``output``, read_file ``content``, ``stdout`` / ``text``) is pruned inside that field
and re-serialised, so the shape the model expects survives. Anything else is pruned as raw text.
"""
import json
import os
import sys
import time

HOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "hooks")
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)
import toollog  # noqa: E402


def _prune_result(result, tool_call_id, session_id, tool_name, args):
    """Pruned replacement for ``result``, or None when it stays as is."""
    try:
        parsed = json.loads(result)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        payload_text = toollog.extract_text(parsed)
        if payload_text:
            if not toollog.needs_pruning(payload_text):
                return None
            pruned_text = toollog.prune(payload_text, tool_call_id, session_id, tool_name, args)
            return json.dumps(toollog.rebuild(parsed, pruned_text), ensure_ascii=False)
    if not toollog.needs_pruning(result):
        return None
    return toollog.prune(result, tool_call_id, session_id, tool_name, args)


def _on_transform_tool_result(tool_name="", args=None, result=None, tool_call_id="", session_id="", **_):
    if os.environ.get("TOOL_LOG_PRUNE") == "0" or not isinstance(result, str):
        return None
    try:
        call_id = tool_call_id or f"hermes-{int(time.time() * 1000)}"
        return _prune_result(result, call_id, session_id, f"hermes:{tool_name}", args)
    except Exception as error:  # never break the tool call; leave output intact
        toollog.log_error("hermes_plugin", error)
        return None


def register(ctx):
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
