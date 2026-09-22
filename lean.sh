# Shell functions that turn `claude --lean`, `codex --lean` and `opencode --lean` into a real flag.
# Sourced from ~/.zshrc by install.py.
#
# The agents reject unknown CLI flags, so the flag is handled here: the function strips `--lean`,
# sets TOOL_LOG_PRUNE=1 for that one process, and runs the real binary. Without `--lean` the
# binary runs exactly as before; the registered hooks see no TOOL_LOG_PRUNE and do nothing.
#
# Tuning: TOOL_LOG_HEAD=1000  TOOL_LOG_TAIL=1000  TOOL_LOG_THRESHOLD=2500  (tokens), e.g.
#   TOOL_LOG_HEAD=500 claude --lean

TOOL_LOG_DIR="${TOOL_LOG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)}"

_tool_log_run() {
  local binary="$1"; shift
  local lean=0 arguments=()
  for argument in "$@"; do
    if [ "$argument" = "--lean" ]; then lean=1; else arguments+=("$argument"); fi
  done
  if [ "$lean" = 1 ]; then
    TOOL_LOG_PRUNE=1 command "$binary" "${arguments[@]}"
  else
    command "$binary" "$@"
  fi
}

claude()   { _tool_log_run claude "$@"; }
codex()    { _tool_log_run codex "$@"; }
opencode() { _tool_log_run opencode "$@"; }

# Fetch an archived tool result:  recall <id> [--chunk K/N | --grep PATTERN | --range A B]   |   recall-list [N]
recall()      { python3 "$TOOL_LOG_DIR/toollog.py" recall "$@"; }
recall-list() { python3 "$TOOL_LOG_DIR/toollog.py" list "$@"; }
