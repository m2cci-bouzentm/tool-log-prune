# tool-log-prune

Keep large tool results out of the model context. Archive them in full, keyed by tool call id, and show the model only the first and last 500 tokens plus a footer that says exactly how to fetch the rest.

Works for Claude Code, Codex and OpenCode from one shared implementation. Off by default. Active only when the agent is started with `TOOL_LOG_PRUNE=1` in its environment: `TOOL_LOG_PRUNE=1 claude`.

## The idea

I had seen tools that prune tool results out of the chat history as a session goes on. The reasoning is sound: ten messages later, do you still need the 40k-character snapshot or the full file you read once? Mostly not.

The problem is the prompt cache. An agent session is one long prefix that the provider caches. Rewrite or delete a result that is already in the history and the prefix changes from that point on, so every later call re-reads everything after it at full price. Pruning after the fact costs more than it saves.

So the idea behind this hook: prune before the result ever enters the context, and save the full text somewhere in case it is still needed. The model sees the head and the tail, enough to know whether the call worked and what the end state is, plus a pointer. The rest sits in an archive keyed by the tool call id and comes back on demand, in chunks. The prefix stays append-only, the cache keeps hitting, and nothing is lost.

No classifier, no LLM call, no summary. Deterministic head + tail, off by default, on with one environment variable.

## How it works

```
tool runs → result → hook
                      ├─ fits in head + tail (≤ 1000 tokens): pass through untouched
                      └─ longer: full text → SQLite, id = tool call id
                                 model sees: head 500 tok + "[... truncated ...]" + tail 500 tok + footer
```

The footer the model sees:

```
[tool-log: output truncated. 42,830 chars (~10,707 tokens) archived under id toolu_01AB…;
 shown above: first 500 and last 500 tokens. The middle is NOT lost. Retrieve it with:
  recall toolu_01AB… --chunk K/N      chunk K of the full text split into N equal parts
  recall toolu_01AB… --chunk A-B/N    chunks A through B of N
  recall toolu_01AB…                  everything]
```

`recall` is a two-line shim in `~/.local/bin` written by the installer. Without it (plugin-only install) the footer prints the full `python3 …/hooks/toollog.py recall` path instead.

So the agent reads the third tenth of a 100k log without paying for the rest, or pipes the full text into `grep` itself.

Archive: `~/.claude/tool-logs/tool_log.sqlite`, one table `results(id, session_id, ts, tool_name, tool_input, size_chars, output)`, shared by all three agents.

## Configuration

Environment variables of the process that starts the agent:

| Variable | Default | Meaning |
|---|---|---|
| `TOOL_LOG_PRUNE` | unset | `1` enables pruning; anything else is pass-through |
| `TOOL_LOG_HEAD` | 500 | tokens kept from the start |
| `TOOL_LOG_TAIL` | 500 | tokens kept from the end |

A result is pruned when it is longer than head + tail.
Tokens are estimated as characters / 4. Example: `TOOL_LOG_PRUNE=1 TOOL_LOG_HEAD=1000 TOOL_LOG_TAIL=1000 claude`.

## Per agent

| Agent | Mechanism | File |
|---|---|---|
| Claude Code | plugin with a `PostToolUse` hook, reply `hookSpecificOutput.updatedToolOutput` | `hooks/hooks.json`, `hooks/prune.py` |
| Codex | `PostToolUse` hook, reply `{"continue": false, "reason": …}` | same `hooks/prune.py` (Codex events carry `turn_id`) |
| OpenCode | plugin `tool.execute.after`, mutates `output.output` / `content[i].text` | `opencode/prune-tool-output.ts` |

All logic is in `hooks/toollog.py`. The hook script imports it; the OpenCode plugin runs inside Bun and calls it as a subprocess (`toollog.py prune-text`).

### Claude Code

`updatedToolOutput` must have the same shape as the original `tool_response`, otherwise Claude Code logs "does not match output shape; using original output". Bash returns `{stdout, stderr, …}`, Read returns `{file: {content, …}}`, MCP tools return `[{type: "text", text}]`. `toollog.rebuild` puts the pruned text back inside a copy of the original structure. Needs Claude Code ≥ 2.1.198.

### Codex

Codex only runs hooks it trusts. The installer writes the trust entry to `~/.codex/config.toml` the same way the TUI `/hooks` review does (sha256 of the canonical hook identity). Changing the hook command, timeout or statusMessage changes the hash; re-run the installer.

Caveat: Codex applies PostToolUse feedback only on the function-tool path. Models catalogued as `code_mode_only` (gpt-6-astra and most current ones) run tools through code mode, where the hook fires and archives but the replacement is discarded by design. Direct-mode models (gpt-5.5) work: `TOOL_LOG_PRUNE=1 codex -m gpt-5.5`.

### OpenCode

For MCP tools OpenCode rebuilds the text from `result.content[]`, so the plugin mutates `content[i].text` instead of `output.output`.

## Install

Claude Code only, as a plugin:

```
claude plugin marketplace add m2cci-bouzentm/tool-log-prune
claude plugin install tool-log-prune@tool-log-prune --scope user
```

All three agents:

```
git clone https://github.com/m2cci-bouzentm/tool-log-prune && cd tool-log-prune && python3 install.py
```

The installer runs the two plugin commands above for Claude Code, registers and trusts the Codex hook in `~/.codex/hooks.json` pointing at the clone, symlinks the OpenCode plugin into `~/.config/opencode/plugins/`, and puts `recall` in `~/.local/bin`. It is idempotent. Then:

```
TOOL_LOG_PRUNE=1 claude               # Claude Code with pruning
TOOL_LOG_PRUNE=1 codex -m gpt-5.5     # Codex with pruning, direct-mode model
TOOL_LOG_PRUNE=1 opencode             # OpenCode with pruning
claude                                # plain, unchanged
recall <id> --chunk 2/5
```

The binaries reject unknown flags, so the switch is the environment variable, set inline for one process. The hooks are registered permanently but do nothing without it.

## Verified end to end

Every row was run against the real agent binary, no mocks, and checked from the raw transcript or the agent's printed output, not the model's self-report. Head 1000 / tail 1000 at the time; the default is now 500 / 500.

| Agent | Tool | `TOOL_LOG_PRUNE=1` | unset |
|---|---|---|---|
| Claude Code 2.1.280 | Bash 12,000 chars | 8,699 chars + footer, archived | 12,000 chars, nothing archived |
| Claude Code 2.1.280 | Read 25,096 chars | 9,031 chars + footer, archived | 25,096 chars, nothing archived |
| Claude Code 2.1.280 | MCP snapshot 42,830 chars | 8,997 chars + footer, archived | 42,830 chars, nothing archived |
| Codex 0.154.0, gpt-5.5 | shell 12,000 chars | footer present, archived | untouched, nothing archived |
| OpenCode 1.18.30 | bash 12,000 chars | 4,000-char runs + footer, archived | 12,000 chars, nothing archived |

## Measured token reduction

Replayed against 65 local Claude Code session transcripts (11,054 tool results, internal coding projects and home-directory sessions), read-only. The hook's rule is applied to every tool result: longer than head + tail → keep head + tail plus a ~700-char footer. Tokens are chars / 4. The transcripts already carry Claude Code's own limits (Bash spilled above 30 KB, Read capped at 25k tokens per call), so the numbers are on top of those.

Two configurations, everything else equal:

| | head 1000 / tail 1000 | head 500 / tail 500 (default) |
|---|---|---|
| pruned when longer than | 2,000 tokens (8,000 chars) | 1,000 tokens (4,000 chars) |
| results pruned | 335 of 11,054 (3.0%) | 806 (7.3%) |
| tool-result tokens entering context, paid once | 3,663,843 → 2,861,549 (−21.9%) | → 2,451,446 (−33.1%) |
| same tokens re-sent on every later API call (prefix-cache reads), upper bound without compaction | −31.9% | −43.9% |
| mean saving per session | 8.2% | 17.1% |
| median saving per session | 1.1% | 10.3% |

Per tool type:

| tool | results | avg tokens / result | pruned at 1000 / 1000 | saving | pruned at 500 / 500 | saving |
|---|---|---|---|---|---|---|
| Read | 530 | 2,045 | 163 | 47.5% | 234 | 64.5% |
| subagent output (TaskOutput) | 19 | 1,572 | 4 | 59.6% | 4 | 73.0% |
| MCP, browser server | 1,308 | 245 | 39 | 19.7% | 82 | 33.7% |
| MCP, CRM server | 2,085 | 342 | 47 | 19.8% | 185 | 27.8% |
| Bash | 5,139 | 271 | 107 | 7.6% | 295 | 17.9% |
| WebFetch | 126 | 296 | 0 | 0% | 1 | 2.0% |
| Edit, Write | 1,344 | 48 | 0 | 0% | 0 | 0% |

Per session, the 12 largest:

| session | tool results | API calls | tokens in | saving 1000 / 1000 | saving 500 / 500 |
|---|---|---|---|---|---|
| home, long mixed session | 2,900 | 4,131 | 1,614,399 | 37% | 50% |
| internal, backend | 1,134 | 2,160 | 215,585 | 7% | 19% |
| internal, backend | 672 | 1,199 | 142,616 | 8% | 15% |
| internal, backend | 428 | 857 | 147,517 | 27% | 38% |
| internal, backend | 388 | 848 | 144,016 | 7% | 20% |
| internal, backend | 451 | 696 | 100,100 | 13% | 24% |
| internal, backend | 426 | 869 | 74,000 | 2% | 6% |
| internal, backend | 433 | 839 | 73,005 | 1% | 13% |
| home | 312 | 584 | 73,673 | 2% | 9% |
| internal, worktree | 157 | 278 | 52,369 | 27% | 34% |
| internal, small session | 38 | 65 | 49,804 | 35% | 54% |
| internal, backend | 139 | 268 | 53,716 | 19% | 33% |

Read is where the hook pays. Bash is mostly handled by the harness already. Edit and Write never cross the limit. A plain coding session gains 2–10% at 1000 / 1000 and 10–20% at 500 / 500; sessions that read big files, pull MCP data or run long gain 25–50%. Halving head and tail doubles the typical saving at the cost of 2.4x more results being cut, so more recall calls when the middle matters. The re-sent row assumes no compaction, so it overstates very long sessions; the entering-context row is the conservative one.

## Files

```
.claude-plugin/plugin.json        Claude Code plugin manifest
.claude-plugin/marketplace.json   self-hosted marketplace (this repo is the only entry)
hooks/hooks.json                  PostToolUse hook definition, ${CLAUDE_PLUGIN_ROOT}/hooks/prune.py
hooks/prune.py                    the hook, Claude Code and Codex
hooks/toollog.py                  shared module + CLI (prune, archive, recall)
opencode/prune-tool-output.ts     OpenCode plugin
install.py                        installs for all three agents
```

## Related

- [jev-pruner](https://github.com/xmacna/jev-pruner): Bash only, uses TypeSafe Jev to choose which chunks to keep.
- [squeez](https://github.com/claudioemmanuel/squeez): hook-based compressor for 7 hosts, command-aware.
- [semtrim](https://github.com/postman-cs/semtrim): semantic filters per command family.
- [fast-jev-compaction](https://github.com/5seg/fast-jev-compaction): Jev-scored compaction instead of a summary.
