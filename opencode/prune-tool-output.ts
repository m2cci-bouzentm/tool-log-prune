// OpenCode plugin: prune large tool results via the shared hooks/toollog.py (one implementation for all agents).
// Symlinked into ~/.config/opencode/plugins/ by install.py; resolves toollog.py relative to its real path.
//
// Built-in tools: mutating output.output replaces what the model sees.
// MCP tools: OpenCode rebuilds the text from result.content[], so content[i].text is mutated instead.
import type { Plugin } from "@opencode-ai/plugin"
import { realpathSync } from "node:fs"
import { dirname, join } from "node:path"

const TOOLLOG_PATH = join(dirname(realpathSync(import.meta.path)), "..", "hooks", "toollog.py")

/** Returns the pruned text, or null when the result is below threshold, pruning is disabled, or the helper failed. */
function pruneText(fullText: string, callID: string, sessionID: string, toolName: string): string | null {
  const helper = Bun.spawnSync(
    ["python3", TOOLLOG_PATH, "prune-text", "--id", callID, "--tool", "opencode:" + toolName, "--session", sessionID],
    { stdin: Buffer.from(fullText), env: process.env },
  )
  if (helper.exitCode !== 0) return null
  const prunedText = helper.stdout.toString()
  return prunedText.length > 0 ? prunedText : null
}

export const PruneToolOutput: Plugin = async () => ({
  "tool.execute.after": async (input, output) => {
    if (process.env.TOOL_LOG_PRUNE !== "1") return
    const toolResult = output as any
    try {
      if (typeof toolResult.output === "string") {
        const prunedText = pruneText(toolResult.output, input.callID, input.sessionID, input.tool)
        if (prunedText !== null) toolResult.output = prunedText
        return
      }
      if (Array.isArray(toolResult.content)) {
        for (const contentBlock of toolResult.content) {
          if (contentBlock?.type === "text" && typeof contentBlock.text === "string") {
            const prunedText = pruneText(contentBlock.text, input.callID, input.sessionID, input.tool)
            if (prunedText !== null) contentBlock.text = prunedText
          }
        }
      }
    } catch {
      // never break the tool call; leave output intact
    }
  },
})
