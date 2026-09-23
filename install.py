#!/usr/bin/env python3
"""Install tool-log-prune for Claude Code, Codex and OpenCode.

Claude Code: installed as a plugin from this repo's marketplace (`claude plugin ...`), the
same way any published plugin is. Codex and OpenCode have no equivalent that works without a
manual trust step, so they are registered to point at this clone. Nothing is active until an
agent is started with TOOL_LOG_PRUNE=1 in its environment, e.g. `TOOL_LOG_PRUNE=1 claude`.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
MARKETPLACE = "m2cci-bouzentm/tool-log-prune"
PLUGIN = "tool-log-prune@tool-log-prune"
OLD_HOOK_MARKERS = ("claude_hook.py", "codex_hook.py", "tool-log/prune.py", "prune_tool_output.py", "hooks/prune.py")


def load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def save_json(path, data):
    with open(path, "w") as json_file:
        json.dump(data, json_file, indent=2)


def is_our_hook_group(group):
    return any(any(marker in handler.get("command", "") for marker in OLD_HOOK_MARKERS) for handler in group.get("hooks", []))


def install_claude():
    """Plugin install through the marketplace; drop any hand-registered hook from earlier versions."""
    settings_path = f"{HOME}/.claude/settings.json"
    settings = load_json(settings_path, {})
    groups = settings.get("hooks", {}).get("PostToolUse", [])
    if any(is_our_hook_group(group) for group in groups):
        groups[:] = [group for group in groups if not is_our_hook_group(group)]
        save_json(settings_path, settings)
        print("  Claude Code: removed the hand-registered hook from ~/.claude/settings.json")
    if not shutil.which("claude"):
        print("  Claude Code: `claude` not on PATH, run manually:")
        print(f"    claude plugin marketplace add {MARKETPLACE} && claude plugin install {PLUGIN} --scope user")
        return
    subprocess.run(["claude", "plugin", "marketplace", "add", MARKETPLACE], check=False, capture_output=True)
    subprocess.run(["claude", "plugin", "marketplace", "update", "tool-log-prune"], check=False, capture_output=True)
    install = subprocess.run(["claude", "plugin", "install", PLUGIN, "--scope", "user"], capture_output=True, text=True)
    if "already installed" in install.stdout + install.stderr:
        install = subprocess.run(["claude", "plugin", "update", PLUGIN], capture_output=True, text=True)
    outcome = (install.stdout + install.stderr).strip().splitlines()
    print("  Claude Code:", outcome[-1] if outcome else f"plugin {PLUGIN} installed")


def register_codex_post_tool_use(hooks_path, handler):
    """Replace any earlier registration of ours with `handler`; return its group index."""
    config = load_json(hooks_path, {"hooks": {}})
    groups = config.setdefault("hooks", {}).setdefault("PostToolUse", [])
    groups[:] = [group for group in groups if not is_our_hook_group(group)]
    groups.append({"hooks": [handler]})
    save_json(hooks_path, config)
    return len(groups) - 1


def trust_codex_hook(hooks_path, handler, group_index):
    """Write the trust entry the TUI /hooks review would write, so `codex exec` runs the hook."""
    hook_identity = {"event_name": "post_tool_use", "hooks": [{**handler, "async": False}]}
    canonical_json = json.dumps(hook_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    trusted_hash = "sha256:" + hashlib.sha256(canonical_json.encode()).hexdigest()
    state_key = f"{hooks_path}:post_tool_use:{group_index}:0"
    config_path = f"{HOME}/.codex/config.toml"
    config_text = open(config_path).read() if os.path.exists(config_path) else ""
    stale_block = r'\n\[hooks\.state\."' + re.escape(state_key) + r'"\]\n(?:[^\[\n]*\n)*'
    config_text = re.sub(stale_block, "\n", config_text).rstrip("\n")
    config_text += f'\n\n[hooks.state."{state_key}"]\nenabled = true\ntrusted_hash = "{trusted_hash}"\n'
    with open(config_path, "w") as config_file:
        config_file.write(config_text)


def install_codex():
    if not os.path.isdir(f"{HOME}/.codex"):
        print("  Codex: ~/.codex not found, skipped")
        return
    hooks_path = f"{HOME}/.codex/hooks.json"
    handler = {"type": "command", "command": f"python3 {REPO_DIR}/hooks/prune.py", "timeout": 10, "statusMessage": "Pruning tool output"}
    group_index = register_codex_post_tool_use(hooks_path, handler)
    trust_codex_hook(hooks_path, handler, group_index)
    print("  Codex: PostToolUse hook ->", handler["command"], "(trusted)")


def install_opencode():
    config_dir = f"{HOME}/.config/opencode"
    if not os.path.isdir(config_dir):
        print("  OpenCode: ~/.config/opencode not found, skipped")
        return
    plugin_link = f"{config_dir}/plugins/prune-tool-output.ts"
    os.makedirs(os.path.dirname(plugin_link), exist_ok=True)
    if os.path.lexists(plugin_link):
        os.remove(plugin_link)
    os.symlink(f"{REPO_DIR}/opencode/prune-tool-output.ts", plugin_link)
    config_path = f"{config_dir}/opencode.json"
    config = load_json(config_path, {})
    plugin_list = config.setdefault("plugin", [])
    if "./plugins/prune-tool-output.ts" not in plugin_list:
        plugin_list.append("./plugins/prune-tool-output.ts")
    save_json(config_path, config)
    print("  OpenCode: plugin symlinked into ~/.config/opencode/plugins and registered")


def install_recall_command():
    """`recall <id> [--chunk K/N]` on PATH, so the footer can print a short command."""
    bin_dir = f"{HOME}/.local/bin"
    os.makedirs(bin_dir, exist_ok=True)
    shim_path = f"{bin_dir}/recall"
    with open(shim_path, "w") as shim:
        shim.write(f'#!/bin/sh\nexec python3 "{REPO_DIR}/hooks/toollog.py" recall "$@"\n')
    os.chmod(shim_path, 0o755)
    on_path = bin_dir in os.environ.get("PATH", "").split(os.pathsep)
    print(f"  recall: {shim_path}" + ("" if on_path else "  (add ~/.local/bin to PATH)"))


if __name__ == "__main__":
    install_claude()
    install_codex()
    install_opencode()
    install_recall_command()
    print("done. Start with: TOOL_LOG_PRUNE=1 claude | TOOL_LOG_PRUNE=1 codex -m gpt-5.5 | TOOL_LOG_PRUNE=1 opencode")
