# tool-log-prune

Keep large tool results out of the model context. Archive them in full, keyed by tool call id, and show the model only the first 500 and last 500 tokens plus a pointer to the full text.

Works for Claude Code, Codex and OpenCode. Off by default. Active only when the agent is started with `TOOL_LOG_PRUNE=1` (the `*-lean` wrappers below).

## Why

Tool results are the part of an agent's context that grows without bound. One browser snapshot is 20k+ tokens, a test log 30k, and most of it is read once. Compaction and summaries come too late and are lossy. This hook trims at insertion time, so:

- the prompt-cache prefix stays append-only (nothing already in context is rewritten),
- nothing is lost: the full result is on disk and can be fetched by id,
- the model still sees enough to know whether the call succeeded (head) and what the final state is (tail).

No classifier, no LLM call. Deterministic head + tail.

## How it works

```
tool runs → result → [hook]
                       ├─ ≤ 1000 tokens: pass through untouched
                       └─ > 1000 tokens: write full text to SQLite (id = tool call id)
                                          replace with: head 500 tok + "[... truncated ...]" + tail 500 tok + footer
footer: [tool-log: 27,889 chars archived, showing first 500 and last 500 tokens. id=toolu_01AB…
         Full text: python3 ~/.claude/hooks/tool-log/recall.py toolu_01AB… [--grep PATTERN]]
```

Archive: `~/.claude/tool-logs/tool_log.sqlite`, one table `results(id, session_id, ts, tool_name, tool_input, size_chars, output)`. Shared by all three agents.

Recall:

```
recall <id>                    full text
recall <id> --grep PATTERN     matching lines with line numbers
recall <id> --range A B        character range
recall --list [N]              last N archived results
recall --session <session_id>
```

Tokens are estimated as chars / 4. Thresholds are constants at the top of each hook file.

## Per agent

| Agent | Mechanism | File | Status |
|---|---|---|---|
| Claude Code | `PostToolUse` hook, `hookSpecificOutput.updatedToolOutput` | `claude/prune.py` | verified, Bash + MCP tools |
| Codex | `PostToolUse` hook, `{"continue": false, "reason": …}` | `codex/prune_tool_output.py` | verified in direct tool mode, see caveat |
| OpenCode | plugin `tool.execute.after`, mutates `output.output` / `content[i].text` | `opencode/prune-tool-output.ts` | verified, built-in + MCP tools |

### Claude Code

`updatedToolOutput` must have the same shape as the original `tool_response`, otherwise Claude Code logs "does not match output shape; using original output". Bash returns `{stdout, stderr, …}`, MCP tools return `[{type: "text", text}]`. The hook rebuilds the same structure with only the text swapped. Needs Claude Code ≥ 2.1.198. `Read`, `Edit`, `Write` are skipped: the model asked for that content verbatim, truncating it only causes a re-read.

### Codex

Codex only runs hooks it trusts. The installer writes the trust entry to `~/.codex/config.toml` the same way the TUI `/hooks` review does (sha256 of the canonical hook identity). Change the hook command, timeout or statusMessage and the hash changes; re-run the installer.

Caveat: Codex applies PostToolUse feedback only on the function-tool path. Models catalogued as `code_mode_only` (gpt-6-astra and most current ones) run tools through code mode, where the hook fires and archives but the replacement is discarded by design. Direct-mode models (gpt-5.5) work: `codex-lean -m gpt-5.5`.

### OpenCode

Plugins run inside OpenCode's Bun binary, so the plugin uses `bun:sqlite` and writes to the same archive. For MCP tools OpenCode rebuilds the text from `result.content[]`, so the plugin mutates `content[i].text` instead of `output.output`.

## Install

```
git clone <this repo> && cd tool-log-prune && ./install.sh
```

The installer copies the files, registers the hook/plugin in each agent's config, trusts the Codex hook, and sources `lean.sh` from `~/.zshrc`. Then, in a new shell:

```
claude-lean      # Claude Code with pruning
codex-lean       # Codex with pruning (use a direct-mode model)
opencode-lean    # OpenCode with pruning
claude           # plain, unchanged
```

## Verified end to end

Every combination below was run against the real agent binary, no mocks, and checked from the raw transcript or the agent's own output, not the model's self-report:

| Agent | Tool | With flag | Without flag |
|---|---|---|---|
| Claude Code 2.1.280 | Bash 9,000 chars | 4,234 chars + footer, archived | 9,000 chars, nothing archived |
| Claude Code 2.1.280 | MCP snapshot 43k chars | 4,235 chars + footer, archived | 42,862 chars, nothing archived |
| Codex 0.154.0, gpt-5.5 | shell 9,000 chars | footer present, archived | untouched, nothing archived |
| OpenCode 1.18.30 | bash 9,000 chars | truncated + footer, archived | 9,000 chars, nothing archived |

## Files

```
claude/prune.py               Claude Code PostToolUse hook
codex/prune_tool_output.py    Codex PostToolUse hook
opencode/prune-tool-output.ts OpenCode plugin
recall.py                     fetch archived results by id
lean.sh                       claude-lean / codex-lean / opencode-lean / recall
install.sh                    copies, registers, trusts
```
