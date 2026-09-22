# tool-log-prune

Keep large tool results out of the model context. Archive them in full, keyed by tool call id, and show the model only the first and last 1000 tokens plus a footer that says exactly how to fetch the rest.

Works for Claude Code, Codex and OpenCode from one shared implementation. Off by default. Active only when the agent is started with `TOOL_LOG_PRUNE=1` in its environment: `TOOL_LOG_PRUNE=1 claude`.

## Why

Tool results are the part of an agent's context that grows without bound. One browser snapshot is 40k characters, a file read 25k, a test log 30k, and most of it is read once. Compaction and summaries come too late and are lossy. This hook trims at insertion time, so:

- the prompt-cache prefix stays append-only: nothing already in context is ever rewritten,
- nothing is lost: the full result is on disk and can be fetched by id, in chunks,
- the model still sees enough to know whether the call succeeded (head) and what the final state is (tail).

No classifier, no LLM call. Deterministic head + tail.

## How it works

```
tool runs → result → hook
                      ├─ fits in head + tail (≤ 2000 tokens): pass through untouched
                      └─ longer: full text → SQLite, id = tool call id
                                 model sees: head 1000 tok + "[... truncated ...]" + tail 1000 tok + footer
```

The footer the model sees:

```
[tool-log: output truncated. 42,830 chars (~10,707 tokens) archived under id toolu_01AB…;
 shown above: first 1000 and last 1000 tokens. The middle is NOT lost. Retrieve it with:
  python3 /…/toollog.py recall toolu_01AB… --chunk K/N      chunk K of the full text split into N equal parts
  python3 /…/toollog.py recall toolu_01AB… --chunk A-B/N    chunks A through B of N
  python3 /…/toollog.py recall toolu_01AB…                  everything]
```

So the agent reads the third tenth of a 100k log without paying for the rest, or pipes the full text into `grep` itself.

Archive: `~/.claude/tool-logs/tool_log.sqlite`, one table `results(id, session_id, ts, tool_name, tool_input, size_chars, output)`, shared by all three agents.

## Configuration

Environment variables of the process that starts the agent:

| Variable | Default | Meaning |
|---|---|---|
| `TOOL_LOG_PRUNE` | unset | `1` enables pruning; anything else is pass-through |
| `TOOL_LOG_HEAD` | 1000 | tokens kept from the start |
| `TOOL_LOG_TAIL` | 1000 | tokens kept from the end |

A result is pruned when it is longer than head + tail.
Tokens are estimated as characters / 4. Example: `TOOL_LOG_PRUNE=1 TOOL_LOG_HEAD=500 TOOL_LOG_TAIL=300 claude`.

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

Caveat: Codex applies PostToolUse feedback only on the function-tool path. Models catalogued as `code_mode_only` (gpt-6-astra and most current ones) run tools through code mode, where the hook fires and archives but the replacement is discarded by design. Direct-mode models (gpt-5.5) work: `TOOL_LOG_PRUNE=1 codex -m gpt-5.5`.

### OpenCode

For MCP tools OpenCode rebuilds the text from `result.content[]`, so the plugin mutates `content[i].text` instead of `output.output`.

## Install

```
git clone https://github.com/m2cci-bouzentm/tool-log-prune && cd tool-log-prune && python3 install.py
```

The installer registers the hooks pointing at the clone (no copies, `git pull` updates all three), trusts the Codex hook and symlinks the OpenCode plugin. It is idempotent. Then:

```
TOOL_LOG_PRUNE=1 claude               # Claude Code with pruning
TOOL_LOG_PRUNE=1 codex -m gpt-5.5     # Codex with pruning, direct-mode model
TOOL_LOG_PRUNE=1 opencode             # OpenCode with pruning
claude                                # plain, unchanged
python3 toollog.py recall <id> --chunk 2/5
```

The binaries reject unknown flags, so the switch is the environment variable, set inline for one process. The hooks are registered permanently but do nothing without it.

## Verified end to end

Every row was run against the real agent binary, no mocks, and checked from the raw transcript or the agent's printed output, not the model's self-report.

| Agent | Tool | `TOOL_LOG_PRUNE=1` | unset |
|---|---|---|---|
| Claude Code 2.1.280 | Bash 12,000 chars | 8,699 chars + footer, archived | 12,000 chars, nothing archived |
| Claude Code 2.1.280 | Read 25,096 chars | 9,031 chars + footer, archived | 25,096 chars, nothing archived |
| Claude Code 2.1.280 | MCP snapshot 42,830 chars | 8,997 chars + footer, archived | 42,830 chars, nothing archived |
| Codex 0.154.0, gpt-5.5 | shell 12,000 chars | footer present, archived | untouched, nothing archived |
| OpenCode 1.18.30 | bash 12,000 chars | 4,000-char runs + footer, archived | 12,000 chars, nothing archived |

## Measured token reduction

Replayed against 65 real Claude Code session transcripts from one machine (11,054 tool results, coding work on internal projects plus home-directory sessions). Read-only, nothing was modified.

Settings used for every number below. Change them and the tables change.

| setting | value used |
|---|---|
| `TOOL_LOG_HEAD` | 1000 tokens (4,000 chars) |
| `TOOL_LOG_TAIL` | 1000 tokens (4,000 chars) |
| prune when result longer than | head + tail = 2,000 tokens (8,000 chars) |
| footer added to a pruned result | ~700 chars |
| token estimate | chars / 4 |
| Claude Code version of the transcripts | up to 2.1.280, with its own limits already applied (Bash spilled above 30 KB, Read capped at 25k tokens per call) |

| metric | value |
|---|---|
| tool results longer than 8k chars | 335 of 11,054 (3.0%) |
| tool-result tokens entering context, all sessions | 3,663,843 → 2,861,549 (−21.9%) |
| same tokens re-sent on every later API call (prefix cache reads), upper bound without compaction | −31.9% |
| mean saving per session | 8.2% |
| median saving per session | 1.1% |

Per session, the 12 largest:

| session | tool results | >8k | API calls | tokens in | tokens after | saving |
|---|---|---|---|---|---|---|
| home, long mixed session | 2,900 | 182 | 4,131 | 1,614,399 | 1,013,237 | 37% |
| internal, backend | 1,134 | 19 | 2,160 | 215,585 | 200,351 | 7% |
| internal, backend | 672 | 6 | 1,199 | 142,616 | 130,968 | 8% |
| internal, backend | 428 | 12 | 857 | 147,517 | 107,406 | 27% |
| internal, backend | 388 | 12 | 848 | 144,016 | 134,113 | 7% |
| internal, backend | 451 | 8 | 696 | 100,100 | 87,364 | 13% |
| internal, backend | 426 | 2 | 869 | 74,000 | 72,737 | 2% |
| internal, backend | 433 | 7 | 839 | 73,005 | 72,043 | 1% |
| home | 312 | 3 | 584 | 73,673 | 71,881 | 2% |
| internal, worktree | 157 | 4 | 278 | 52,369 | 38,401 | 27% |
| internal, small session | 38 | 9 | 65 | 49,804 | 32,515 | 35% |
| internal, backend | 139 | 7 | 268 | 53,716 | 43,620 | 19% |

Per tool type, all sessions combined:

| tool | results | >8k | avg tokens / result | tokens before | tokens after | saving |
|---|---|---|---|---|---|---|
| Read | 530 | 163 | 2,045 | 1,084,317 | 569,782 | 47.5% |
| subagent output (TaskOutput) | 19 | 4 | 1,572 | 29,878 | 12,056 | 59.6% |
| MCP, CRM server | 2,085 | 47 | 342 | 713,229 | 572,138 | 19.8% |
| MCP, browser server | 1,308 | 39 | 245 | 321,485 | 258,299 | 19.7% |
| Bash | 5,135 | 107 | 271 | 1,395,996 | 1,290,424 | 7.6% |
| Edit | 923 | 0 | 49 | 45,409 | 45,409 | 0% |
| Write | 419 | 0 | 46 | 19,320 | 19,320 | 0% |

Same replay with `TOOL_LOG_HEAD=500 TOOL_LOG_TAIL=500` (prune above 4,000 chars), everything else unchanged:

| metric | 1000 / 1000 | 500 / 500 |
|---|---|---|
| results above the limit | 335 (3.0%) | 806 (7.3%) |
| tokens inserted | −21.9% | −33.1% |
| mean saving per session | 8.2% | 17.1% |
| median saving per session | 1.1% | 10.3% |

| tool | results | >limit at 500/500 | saving 1000/1000 | saving 500/500 |
|---|---|---|---|---|
| Read | 530 | 234 | 47.5% | 64.5% |
| subagent output (TaskOutput) | 19 | 4 | 59.6% | 73.0% |
| MCP, browser server | 1,308 | 82 | 19.7% | 33.7% |
| MCP, CRM server | 2,085 | 185 | 19.8% | 27.8% |
| Bash | 5,139 | 295 | 7.6% | 17.9% |
| WebFetch | 126 | 1 | 0% | 2.0% |
| Edit, Write | 1,344 | 0 | 0% | 0% |

Halving head and tail moves the median session from 1% to 10% and Bash from 8% to 18%, at the price of 2.4x more results being cut (806 vs 335), so more recall calls when the middle matters.

What this means:

- A typical coding session gains 2–10% at 1000/1000, 10–20% at 500/500. Only 3% of results are big enough to trim, because Claude Code already spills Bash output above 30 KB to a file and caps Read at 25k tokens per call.
- Sessions that read big files, pull MCP data (CRM inboxes, browser snapshots) or run long: 25–37%.
- Read is the main win. Bash is mostly handled by the harness already.
- The re-sent figure assumes no compaction, so it overstates very long sessions; the per-insertion figure is the conservative one.

## Files

```
toollog.py           shared module + CLI (prune, archive, recall)
claude_hook.py       Claude Code PostToolUse hook
codex_hook.py        Codex PostToolUse hook
opencode_plugin.ts   OpenCode plugin
install.py           registers, trusts, symlinks
```

## Related

- [jev-pruner](https://github.com/xmacna/jev-pruner): Bash only, uses TypeSafe Jev to choose which chunks to keep.
- [squeez](https://github.com/claudioemmanuel/squeez): hook-based compressor for 7 hosts, command-aware.
- [semtrim](https://github.com/postman-cs/semtrim): semantic filters per command family.
- [fast-jev-compaction](https://github.com/5seg/fast-jev-compaction): Jev-scored compaction instead of a summary.
