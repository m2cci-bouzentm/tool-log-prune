#!/usr/bin/env python3
"""Install tool-log-prune for Claude Code, OpenCode and Hermes Agent.

Claude Code: installed as a plugin from this repo's marketplace (`claude plugin ...`), the
same way any published plugin is. OpenCode is registered to point at this clone. Nothing is active until an
agent is started with TOOL_LOG_PRUNE=1 in its environment, e.g. `TOOL_LOG_PRUNE=1 claude`.
Hermes is the exception: the plugin is symlinked into ~/.hermes and every profile under
~/.hermes/profiles and enabled there, so it is active for every profile and provider as soon
as it is loaded. Re-run this installer after creating a new Hermes profile.
"""
import json
import os
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


def hermes_homes():
    """~/.hermes plus every profile directory that has its own config.yaml."""
    base = f"{HOME}/.hermes"
    if not os.path.isdir(base):
        return []
    profiles_dir = f"{base}/profiles"
    profile_homes = sorted(
        f"{profiles_dir}/{name}" for name in (os.listdir(profiles_dir) if os.path.isdir(profiles_dir) else [])
        if os.path.exists(f"{profiles_dir}/{name}/config.yaml"))
    return [base] + profile_homes


def install_hermes():
    """Symlink the plugin into every Hermes home and enable it there with Hermes' own CLI."""
    homes = hermes_homes()
    if not homes:
        print("  Hermes: ~/.hermes not found, skipped")
        return
    hermes_binary = shutil.which("hermes")
    for home in homes:
        plugin_link = f"{home}/plugins/tool-log-prune"
        os.makedirs(os.path.dirname(plugin_link), exist_ok=True)
        if os.path.lexists(plugin_link):
            os.remove(plugin_link)
        os.symlink(f"{REPO_DIR}/hermes/tool-log-prune", plugin_link)
        if hermes_binary:
            enable = subprocess.run([hermes_binary, "plugins", "enable", "tool-log-prune"], capture_output=True, text=True,
                                    env={**os.environ, "HERMES_HOME": home})
            outcome = (enable.stdout + enable.stderr).strip().splitlines()
            print(f"  Hermes {home}: plugin symlinked,", outcome[-1] if outcome else "enabled")
        else:
            print(f"  Hermes {home}: plugin symlinked; run: HERMES_HOME={home} hermes plugins enable tool-log-prune")


if __name__ == "__main__":
    install_claude()
    install_opencode()
    install_hermes()
    install_recall_command()
    print("done. Start with: TOOL_LOG_PRUNE=1 claude | TOOL_LOG_PRUNE=1 opencode | hermes (always on)")
