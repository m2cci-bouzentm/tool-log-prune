# tool-log-prune

Keep large tool results out of the model context. Archive them in full, keyed by tool call id, and show the model only the first and last 1000 tokens plus a footer that says exactly how to fetch the rest.

Works for Claude Code, Codex and OpenCode from one shared implementation. Off by default. Active only when the agent is started with `--lean` (`claude --lean`, `codex --lean`, `opencode --lean`), which sets `TOOL_LOG_PRUNE=1` for that process only.

## Why

Tool results are the part of an agent's context that grows without bound. One browser snapshot is 40k characters, a file read 25k, a test log 30k, and most of it is read once. Compaction and summaries come too late and are lossy. This hook trims at insertion time, so:

- the prompt-cache prefix stays append-only: nothing already in context is ever rewritten,
- nothing is lost: the full result is on disk and can be fetched by id, in chunks,
- the model still sees enough to know whether the call succeeded (head) and what the final state is (tail).

No classifier, no LLM call. Deterministic head + tail.

## How it works

```
tool runs → result → hook
                      ├─ ≤ 2500 tokens: pass through untouched
                      └─ > 2500 tokens: full text → SQLite, id = tool call id
                                        model sees: head 1000 tok + "[... truncated ...]" + tail 1000 tok + footer
```

The footer the model sees:

```
[tool-log: output truncated. 42,830 chars (~10,707 tokens) archived under id toolu_01AB…;
 shown above: first 1000 and last 1000 tokens. The middle is NOT lost. Retrieve it with:
  python3 /…/toollog.py recall toolu_01AB… --chunk K/N      chunk K of the full text split into N equal parts
  python3 /…/toollog.py recall toolu_01AB… --chunk A-B/N    chunks A through B of N
  python3 /…/toollog.py recall toolu_01AB… --grep PATTERN   only lines matching a regex, with line numbers
  python3 /…/toollog.py recall toolu_01AB… --range S E      characters S..E
  python3 /…/toollog.py recall toolu_01AB…                  everything]
```

So the agent reads the third tenth of a 100k log, or the lines matching `Error`, without paying for the rest.

Archive: `~/.claude/tool-logs/tool_log.sqlite`, one table `results(id, session_id, ts, tool_name, tool_input, size_chars, output)`, shared by all three agents. `python3 toollog.py list [N]` shows the latest entries.

## Configuration

Environment variables of the process that starts the agent:

| Variable | Default | Meaning |
|---|---|---|
| `TOOL_LOG_PRUNE` | unset | `1` enables pruning; anything else is pass-through |
| `TOOL_LOG_HEAD` | 1000 | tokens kept from the start |
| `TOOL_LOG_TAIL` | 1000 | tokens kept from the end |
| `TOOL_LOG_THRESHOLD` | 2500 | results at or below this many tokens are never touched |
| `TOOL_LOG_DB` | `~/.claude/tool-logs/tool_log.sqlite` | archive location |
| `TOOL_LOG_DEBUG` | unset | `1` dumps the last raw hook event next to the database |

Tokens are estimated as characters / 4. Example: `TOOL_LOG_HEAD=500 TOOL_LOG_TAIL=300 claude --lean`.

## Per agent

| Agent | Mechanism | File |
|---|---|---|
| Claude Code | `PostToolUse` hook, `hookSpecificOutput.updatedToolOutput` | `claude_hook.py` |
| Codex | `PostToolUse` hook, `{"continue": false, "reason": …}` | `codex_hook.py` |
| OpenCode | plugin `tool.execute.after`, mutates `output.output` / `content[i].text` | `opencode_plugin.ts` |

All logic is in `toollog.py`. The two Python hooks import it; the OpenCode plugin runs inside Bun and calls it as a subprocess (`toollog.py prune-text`).

### Claude Code

`updatedToolOutput` must have the same shape as the original `tool_response`, otherwise Claude Code logs "does not match output shape; using original output". Bash returns `{stdout, stderr, …}`, Read returns `{file: {content, …}}`, MCP tools return `[{type: "text", text}]`. `toollog.rebuild` puts the pruned text back inside a copy of the original structure. Needs Claude Code ≥ 2.1.198.

### Codex

Codex only runs hooks it trusts. The installer writes the trust entry to `~/.codex/config.toml` the same way the TUI `/hooks` review does (sha256 of the canonical hook identity). Changing the hook command, timeout or statusMessage changes the hash; re-run the installer.

Caveat: Codex applies PostToolUse feedback only on the function-tool path. Models catalogued as `code_mode_only` (gpt-6-astra and most current ones) run tools through code mode, where the hook fires and archives but the replacement is discarded by design. Direct-mode models (gpt-5.5) work: `codex --lean -m gpt-5.5`.

### OpenCode

For MCP tools OpenCode rebuilds the text from `result.content[]`, so the plugin mutates `content[i].text` instead of `output.output`.

## Install

```
git clone https://github.com/m2cci-bouzentm/tool-log-prune && cd tool-log-prune && python3 install.py
```

The installer registers the hooks pointing at the clone (no copies, `git pull` updates all three), trusts the Codex hook, symlinks the OpenCode plugin, and sources `lean.sh` from `~/.zshrc`. It is idempotent. Then, in a new shell:

```
claude --lean             # Claude Code with pruning
codex --lean -m gpt-5.5   # Codex with pruning, direct-mode model
opencode --lean           # OpenCode with pruning
claude                    # plain, unchanged
recall <id> --chunk 2/5
recall-list
```

`--lean` is not a flag the binaries know. `lean.sh` defines shell functions named `claude`, `codex` and `opencode` that strip `--lean`, set `TOOL_LOG_PRUNE=1` for that one process, and run the real binary. Without `--lean` they run the binary untouched.

## Verified end to end

Every row was run against the real agent binary, no mocks, and checked from the raw transcript or the agent's printed output, not the model's self-report.

| Agent | Tool | With flag | Without flag |
|---|---|---|---|
| Claude Code 2.1.280 | Bash 12,000 chars | 8,996 chars + footer, archived | 12,000 chars, nothing archived |
| Claude Code 2.1.280 | Read 25,096 chars | 9,336 chars + footer, archived | 25,096 chars, nothing archived |
| Claude Code 2.1.280 | MCP snapshot 42,830 chars | 8,997 chars + footer, archived | 42,830 chars, nothing archived |
| Codex 0.154.0, gpt-5.5 | shell 12,000 chars | footer present, archived | untouched, nothing archived |
| OpenCode 1.18.30 | bash 12,000 chars | 4,000-char runs + footer, archived | 12,000 chars, nothing archived |

## Files

```
toollog.py           shared module + CLI (prune, archive, recall, list)
claude_hook.py       Claude Code PostToolUse hook
codex_hook.py        Codex PostToolUse hook
opencode_plugin.ts   OpenCode plugin
lean.sh              the --lean flag for claude / codex / opencode, plus recall / recall-list
install.py           registers, trusts, symlinks
```

## Related

- [jev-pruner](https://github.com/xmacna/jev-pruner): Bash only, uses TypeSafe Jev to choose which chunks to keep.
- [squeez](https://github.com/claudioemmanuel/squeez): hook-based compressor for 7 hosts, command-aware.
- [semtrim](https://github.com/postman-cs/semtrim): semantic filters per command family.
- [fast-jev-compaction](https://github.com/5seg/fast-jev-compaction): Jev-scored compaction instead of a summary.
