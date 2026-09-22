# Wrapper commands that start an agent with tool-result pruning enabled.
# Source from ~/.zshrc:  source ~/.claude/hooks/tool-log/lean.sh
#
# The PostToolUse hook (~/.claude/hooks/tool-log/prune.py) is registered globally but
# does nothing unless TOOL_LOG_PRUNE=1 is in the agent's environment. These wrappers
# set it only for the process they start, so plain `claude` keeps full tool output.

claude-lean() { TOOL_LOG_PRUNE=1 command claude "$@"; }
codex-lean() { TOOL_LOG_PRUNE=1 command codex "$@"; }
opencode-lean() { TOOL_LOG_PRUNE=1 command opencode "$@"; }

# Fetch an archived tool result:  recall <tool_use_id> [--grep PATTERN]
recall() { python3 "$HOME/.claude/hooks/tool-log/recall.py" "$@"; }
