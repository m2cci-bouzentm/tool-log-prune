// OpenCode plugin: archive large tool results, keep head + tail for the model.
// Same policy and same SQLite archive as the Claude Code hook (~/.claude/hooks/tool-log/prune.py).
// Active only when TOOL_LOG_PRUNE=1 is set in the environment that launched opencode
// (see ~/.claude/hooks/tool-log/lean.sh, `opencode-lean`).
//
// Built-in tools: mutating output.output replaces what the model sees.
// MCP tools: OpenCode rebuilds the text from result.content[], so mutate content[i].text.
import type { Plugin } from "@opencode-ai/plugin"
import { Database } from "bun:sqlite"
import { homedir } from "node:os"
import { mkdirSync } from "node:fs"

const THRESHOLD_CHARS = 1000 * 4
const HEAD_CHARS = 500 * 4
const TAIL_CHARS = 500 * 4
const DB_PATH = `${homedir()}/.claude/tool-logs/tool_log.sqlite`

function store(id: string, sessionID: string, tool: string, args: unknown, text: string) {
  mkdirSync(`${homedir()}/.claude/tool-logs`, { recursive: true })
  const db = new Database(DB_PATH)
  db.run(
    "CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, session_id TEXT, ts REAL, tool_name TEXT, tool_input TEXT, size_chars INTEGER, output TEXT)",
  )
  db.run("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?)", [
    id, sessionID, Date.now() / 1000, "opencode:" + tool, JSON.stringify(args ?? null).slice(0, 4000), text.length, text,
  ])
  db.close()
}

function prune(text: string, id: string, sessionID: string, tool: string, args: unknown): string {
  store(id, sessionID, tool, args, text)
  const footer =
    `\n\n[tool-log: ${text.length.toLocaleString()} chars archived, showing first 500 and last 500 tokens.` +
    ` id=${id}. Full text: python3 ~/.claude/hooks/tool-log/recall.py ${id} [--grep PATTERN]]`
  return text.slice(0, HEAD_CHARS) + "\n\n[... truncated ...]\n\n" + text.slice(-TAIL_CHARS) + footer
}

export const PruneToolOutput: Plugin = async () => ({
  "tool.execute.after": async (input, output) => {
    if (process.env.TOOL_LOG_PRUNE !== "1") return
    if (input.tool === "read" || input.tool === "edit" || input.tool === "write") return
    const o = output as any
    try {
      if (typeof o.output === "string") {
        if (o.output.length > THRESHOLD_CHARS) o.output = prune(o.output, input.callID, input.sessionID, input.tool, input.args)
        return
      }
      if (Array.isArray(o.content)) {
        for (const item of o.content) {
          if (item?.type === "text" && typeof item.text === "string" && item.text.length > THRESHOLD_CHARS) {
            item.text = prune(item.text, input.callID, input.sessionID, input.tool, input.args)
          }
        }
      }
    } catch {
      // never break the tool call; leave output intact
    }
  },
})
