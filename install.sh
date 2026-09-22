#!/bin/bash
# Install tool-log-prune for Claude Code, Codex and OpenCode.
# Copies the hook files into place, registers them, and adds the lean wrappers to ~/.zshrc.
# Nothing is active until you start an agent with TOOL_LOG_PRUNE=1 (claude-lean / codex-lean / opencode-lean).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== Claude Code"
mkdir -p ~/.claude/hooks/tool-log
cp "$HERE/claude/prune.py" "$HERE/recall.py" "$HERE/lean.sh" ~/.claude/hooks/tool-log/
python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.claude/settings.json")
d = json.load(open(p)) if os.path.exists(p) else {}
post = d.setdefault("hooks", {}).setdefault("PostToolUse", [])
cmd = "python3 " + os.path.expanduser("~/.claude/hooks/tool-log/prune.py")
if not any(cmd in h.get("command", "") for e in post for h in e.get("hooks", [])):
    post.append({"hooks": [{"type": "command", "command": cmd, "timeout": 10}]})
    json.dump(d, open(p, "w"), indent=2)
    print("  PostToolUse hook registered in ~/.claude/settings.json")
else:
    print("  already registered")
PY

echo "== Codex"
if [ -d ~/.codex ]; then
  mkdir -p ~/.codex/hooks
  cp "$HERE/codex/prune_tool_output.py" ~/.codex/hooks/
  python3 - <<'PY'
import json, os, hashlib, re
hp = os.path.expanduser("~/.codex/hooks.json")
d = json.load(open(hp)) if os.path.exists(hp) else {"hooks": {}}
post = d.setdefault("hooks", {}).setdefault("PostToolUse", [])
cmd = "python3 " + os.path.expanduser("~/.codex/hooks/prune_tool_output.py")
handler = {"type": "command", "command": cmd, "timeout": 10, "statusMessage": "Pruning tool output"}
idx = next((i for i, e in enumerate(post) if any(cmd in h.get("command", "") for h in e.get("hooks", []))), None)
if idx is None:
    post.append({"hooks": [handler]}); idx = len(post) - 1
    json.dump(d, open(hp, "w"), indent=2)
    print("  PostToolUse hook registered in ~/.codex/hooks.json")
else:
    print("  already registered")
# Trust the hook the same way the TUI /hooks review does, so `codex exec` runs it.
identity = {"event_name": "post_tool_use", "hooks": [{**handler, "async": False}]}
h = "sha256:" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
key = f"{hp}:post_tool_use:{idx}:0"
cp = os.path.expanduser("~/.codex/config.toml")
s = open(cp).read() if os.path.exists(cp) else ""
if key not in s:
    s = s.rstrip("\n") + f'\n\n[hooks.state."{key}"]\nenabled = true\ntrusted_hash = "{h}"\n'
    open(cp, "w").write(s)
    print("  hook trusted in ~/.codex/config.toml")
PY
else
  echo "  ~/.codex not found, skipped"
fi

echo "== OpenCode"
if [ -d ~/.config/opencode ]; then
  mkdir -p ~/.config/opencode/plugins
  cp "$HERE/opencode/prune-tool-output.ts" ~/.config/opencode/plugins/
  python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.config/opencode/opencode.json")
d = json.load(open(p)) if os.path.exists(p) else {}
pl = d.setdefault("plugin", [])
if "./plugins/prune-tool-output.ts" not in pl:
    pl.append("./plugins/prune-tool-output.ts")
    json.dump(d, open(p, "w"), indent=2)
    print("  plugin registered in ~/.config/opencode/opencode.json")
else:
    print("  already registered")
PY
else
  echo "  ~/.config/opencode not found, skipped"
fi

echo "== Shell wrappers"
if ! grep -q 'tool-log/lean.sh' ~/.zshrc 2>/dev/null; then
  printf '\n# tool-result pruning wrappers: claude-lean / codex-lean / opencode-lean / recall\nsource ~/.claude/hooks/tool-log/lean.sh\n' >> ~/.zshrc
  echo "  added to ~/.zshrc (open a new shell)"
else
  echo "  already in ~/.zshrc"
fi
echo "done. Start with: claude-lean | codex-lean | opencode-lean"
