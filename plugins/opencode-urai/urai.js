// Urai plugin for opencode — local AI (chat/agent/vision/imagine/embed) as tools.
//
// Install (project):  cp plugins/opencode-urai/urai.js <proj>/.opencode/plugins/
// Install (global):   cp plugins/opencode-urai/urai.js ~/.config/opencode/plugins/
// Needs: @opencode-ai/plugin (opencode provides it for local plugins).
// Needs: the urai CLI — install.sh, or set URAI_HOME=/path/to/urai.
//
// Ref: https://opencode.ai/docs/plugins/ (custom tools)

import { tool } from "@opencode-ai/plugin"
import { homedir } from "node:os"
import { join } from "node:path"

function cliPath() {
  if (process.env.URAI_HOME) return join(process.env.URAI_HOME, "bin", "urai")
  const local = join(homedir(), ".local", "share", "urai", "bin", "urai")
  return local
}

async function run($, args) {
  const cli = cliPath()
  try {
    const out = await $`${cli} ${args}`.text()
    return out.slice(0, 8000)
  } catch (e) {
    const msg = String((e && e.stderr) || (e && e.message) || e).slice(0, 500)
    if (/no such file/i.test(msg)) {
      throw new Error(
        `urai CLI not found at ${cli} — install it (see urai repo install.sh) or set URAI_HOME`
      )
    }
    throw new Error(msg)
  }
}

const str = (optional) => {
  const s = tool.schema.string()
  return optional ? s.optional() : s
}
const num = (optional) => {
  const s = tool.schema.number()
  return optional ? s.optional() : s
}

export const UraiPlugin = async ({ $ }) => {
  return {
    tool: {
      urai_ask: tool({
        description: "One-shot answer from Urai (local AI, routed backend).",
        args: { text: str(false), max_tokens: num(true) },
        async execute(args) {
          const a = ["ask", args.text]
          return run($, a)
        },
      }),
      urai_agent: tool({
        description: "Multi-step Urai task run (plan/tool/verify loop). Returns answer + trace.",
        args: { task: str(false) },
        async execute(args) {
          return run($, ["agent", args.task])
        },
      }),
      urai_see: tool({
        description: "Ask Urai about a local image file (vision model must be served).",
        args: { image: str(false), question: str(true) },
        async execute(args) {
          return run($, ["see", args.image, args.question || "Describe this image in detail."])
        },
      }),
      urai_imagine: tool({
        description: "Generate a PNG with Urai (stable-diffusion.cpp runner needed).",
        args: { prompt: str(false), out: str(true), seed: num(true) },
        async execute(args) {
          const a = ["imagine", args.prompt]
          if (args.out) a.push("-o", args.out)
          if (args.seed !== undefined) a.push("--seed", String(args.seed))
          return run($, a)
        },
      }),
      urai_embed: tool({
        description: "Embed texts with Urai (embedding server must be up). Returns dims + count.",
        args: { texts: str(false) },
        async execute(args) {
          return run($, ["embed", args.texts])
        },
      }),
      urai_model: tool({
        description: "Urai model registry: list models/kinds/bench numbers (default), or download/use/bench/serve.",
        args: { action: str(true), id: str(true) },
        async execute(args) {
          const a = ["model", args.action || "list"]
          if (args.id) a.push(args.id)
          return run($, a)
        },
      }),
      urai_evaluate: tool({
        description: "Score a task through the Urai agent against expected substrings.",
        args: { task: str(false), expect: str(true) },
        async execute(args) {
          const a = ["evaluate", args.task]
          if (args.expect) a.push("--expect", args.expect)
          return run($, a)
        },
      }),
    },
  }
}
