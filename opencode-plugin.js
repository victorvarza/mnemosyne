/**
 * Mnemosyne OpenCode Plugin
 *
 * Integrates Mnemosyne's memory capabilities with OpenCode: automatic memory
 * storage from conversations, prompt-context injection, and security
 * assessment tools.
 *
 * Follows the OpenCode plugin API (https://opencode.ai/docs/plugins/):
 * a plugin function receives { project, client, $, directory, worktree } and
 * returns a hooks object with top-level keys like `event` and `tool`.
 */

import { tool } from "@opencode-ai/plugin";

/**
 * Extract important information from a message's text parts.
 */
function extractImportantInfo(text) {
  const patterns = [
    /user prefers/i,
    /important.*note/i,
    /remember.*for.*later/i,
    /configuration.*setting/i,
    /project.*convention/i,
    /security.*consideration/i,
    /performance.*optimization/i,
  ];
  for (const pattern of patterns) {
    if (pattern.test(text)) return text;
  }
  return null;
}

/**
 * Pull the text out of an OpenCode message's parts.
 */
async function messageText(client, message) {
  try {
    const { data } = await client.session.message({
      path: { id: message.sessionID, messageID: message.id },
    });
    const parts = (data && data.parts) || [];
    return parts
      .filter((p) => p.type === "text" && p.text)
      .map((p) => p.text)
      .join("\n");
  } catch {
    // Fall back to a content field if present.
    return typeof message.content === "string" ? message.content : "";
  }
}

export const MnemosynePlugin = async ({ project, client, $, directory, worktree }) => {
  await client.app.log({
    body: { service: "mnemosyne", level: "info", message: "Mnemosyne plugin initialized" },
  });

  // Bun shell resolves to Buffers by default; `.text()` yields a string.
  // MNEMO_BIN points at a `mnemo` executable (e.g. the project's .venv/bin/mnemo)
  // when `python3 -m mnemo.cli` can't import mnemo from the session's directory.
  const bin = process.env.MNEMO_BIN;
  const run = (args) =>
    (bin ? $`${bin} ${args}` : $`python3 -m mnemo.cli ${args}`).cwd(directory).text();

  // Latest user-turn text, captured by the `chat.message` hook and consumed by
  // the system-transform hook to retrieve *relevant* memories per turn.
  let lastUserText = "";

  // Fetch the formatted memory block for a query; "" when nothing is relevant.
  // `--` stops user text that starts with "-" from being parsed as a CLI flag.
  // OpenCode transforms the system prompt for every model call in a turn (e.g.
  // title generation and the main reply), so the result is reused per query:
  // one retrieval per user message, and access counts aren't inflated.
  let cached = { query: null, block: null };
  const memoryContext = (query) => {
    if (cached.query === query) return cached.block;
    const block = run(["context", "--top-k", "5", "--", query]).then((out) => {
      const text = out.trim();
      return text ? `## Relevant Context from Memory\n${text}` : "";
    });
    cached = { query, block };
    block.catch(() => {
      if (cached.block === block) cached = { query: null, block: null };
    });
    return block;
  };

  return {
    // --- Custom tools -------------------------------------------------------
    tool: {
      pentest: tool({
        description: "Perform authorized security pentest analysis on source code and a deployed target",
        args: {
          assessmentId: tool.schema.string().describe("Existing authorized assessment identifier"),
          sourcePath: tool.schema.string().describe("Path to the source code directory"),
          targetUrl: tool.schema.string().describe("URL of the deployed target"),
          reportDir: tool.schema.string().optional().describe("Report output directory (default: .)"),
          maxRequests: tool.schema.number().optional().describe("Maximum active HTTP requests (default: 100)"),
          allowPrivateIps: tool.schema.string().optional().describe("Set to 'true' only for authorized labs"),
        },
        async execute(args) {
          const command = [
            "pentest",
            "--assessment",
            args.assessmentId,
            "--source",
            args.sourcePath,
            "--target",
            args.targetUrl,
            "--max-requests",
            String(args.maxRequests ?? 100),
            "--report-dir",
            args.reportDir || ".",
          ];
          if (String(args.allowPrivateIps || "").toLowerCase() === "true") command.push("--allow-private-ips");
          return run(command);
        },
      }),

      assessCreate: tool({
        description: "Create a local authorized security assessment context",
        args: {
          assessmentId: tool.schema.string().describe("Stable identifier for this assessment"),
          target: tool.schema.string().describe("Authorized target identifier or URL"),
          authorized: tool.schema.string().describe("Explicit authorization declaration"),
        },
        async execute(args) {
          return run([
            "assess",
            "create",
            args.assessmentId,
            "--target",
            args.target,
            "--authorized",
            args.authorized,
          ]);
        },
      }),

      assessRecord: tool({
        description: "Record an observation or finding under an authorized assessment",
        args: {
          assessmentId: tool.schema.string().describe("Existing authorized assessment identifier"),
          content: tool.schema.string().describe("Observation, finding, or outcome"),
          kind: tool.schema.string().optional().describe("Record kind (default: observation)"),
          severity: tool.schema.string().optional().describe("Severity (default: info)"),
          evidence: tool.schema.string().optional().describe("Evidence reference"),
          verification: tool.schema.string().optional().describe("Verification status (default: unverified)"),
        },
        async execute(args) {
          return run([
            "assess",
            "record",
            args.assessmentId,
            args.content,
            "--kind",
            args.kind || "observation",
            "--severity",
            args.severity || "info",
            "--evidence",
            args.evidence || "",
            "--verification",
            args.verification || "unverified",
          ]);
        },
      }),

      scan: tool({
        description: "Scan source code for security vulnerabilities (bandit, semgrep, trivy)",
        args: {
          projectPath: tool.schema.string().optional().describe("Project path (default: .)"),
        },
        async execute(args) {
          return run(["scan", "--path", args.projectPath || "."]);
        },
      }),

      securityToolsList: tool({
        description: "List Mnemo registered security tools, optionally by category",
        args: {
          category: tool.schema.string().optional().describe("Optional tool category"),
        },
        async execute(args) {
          const command = ["tools", "list"];
          if (args.category) command.push("--category", args.category);
          return run(command);
        },
      }),

      securityToolRun: tool({
        description: "Run a registered security tool locally or in a Docker/Kali image",
        args: {
          toolName: tool.schema.string().describe("Registered tool name, e.g. nmap, nuclei, bandit"),
          args: tool.schema.string().optional().describe("Raw argument string passed to the tool"),
          mode: tool.schema.string().optional().describe("local or docker (default: docker)"),
          dockerImage: tool.schema.string().optional().describe("Docker image containing security tools"),
          authorization: tool.schema.string().optional().describe("Required for active tools"),
          workdir: tool.schema.string().optional().describe("Directory mounted at /workspace in Docker mode"),
        },
        async execute(args) {
          const command = ["tools", "run", args.toolName, "--mode", args.mode || "docker"];
          if (args.dockerImage) command.push("--docker-image", args.dockerImage);
          if (args.authorization) command.push("--authorized", args.authorization);
          if (args.workdir) command.push("--workdir", args.workdir);
          command.push("--");
          if (args.args) command.push(...args.args.split(/\s+/).filter(Boolean));
          return run(command);
        },
      }),

      remember: tool({
        description: "Manually store a memory in Mnemosyne",
        args: { content: tool.schema.string().describe("The memory content to store") },
        async execute(args) {
          return run(["add", "--", args.content]);
        },
      }),

      recall: tool({
        description: "Manually search memories in Mnemosyne",
        args: {
          query: tool.schema.string().describe("Search query"),
          topK: tool.schema.number().optional().describe("Number of results (default 5)"),
        },
        async execute(args) {
          return run(["search", "--top-k", String(args.topK ?? 5), "--", args.query]);
        },
      }),
    },

    // --- Automatic memory management ---------------------------------------
    // Top-level `event` hook (not nested under `hook`).
    event: async ({ event }) => {
      if (event.type === "session.created") {
        await client.app.log({
          body: { service: "mnemosyne", level: "debug", message: "New session created" },
        });
        return;
      }

      if (event.type === "message.updated") {
        const message = event.message || event.properties?.message || {};
        const role = message.role || event.properties?.role;
        if (role !== "user") return;

        const text = await messageText(client, message);
        const importantInfo = text && extractImportantInfo(text);
        if (!importantInfo) return;

        // Pattern-matched capture: usefulness gating happens at *retrieval*
        // time inside `mnemo context` (the trained Phase 2 model filters and
        // re-ranks there), so storage keeps anything that looks important.
        try {
          await run(["add", "--", `User mentioned: ${importantInfo}`]);
          await client.app.log({
            body: { service: "mnemosyne", level: "info", message: "Stored memory (pattern match)" },
          });
        } catch (error) {
          await client.app.log({
            body: { service: "mnemosyne", level: "warn", message: `Auto-store failed: ${error.message}` },
          });
        }
      }
    },

    // --- Prompt context injection ------------------------------------------
    // Capture each user message so retrieval can target what was actually asked.
    "chat.message": async (input, output) => {
      lastUserText = (output.parts || [])
        .filter((p) => p.type === "text" && p.text)
        .map((p) => p.text)
        .join("\n");
    },

    // Inject memories relevant to the current user turn into the system prompt
    // on every turn (not just at compaction).
    "experimental.chat.system.transform": async (input, output) => {
      if (!lastUserText) return;
      try {
        const block = await memoryContext(lastUserText);
        if (!block) {
          await client.app.log({
            body: { service: "mnemosyne", level: "debug", message: "No relevant memories to inject" },
          });
          return;
        }
        output.system.push(block);
        const count = block.split("\n").filter((line) => line.startsWith("- ")).length;
        await client.app.log({
          body: {
            service: "mnemosyne",
            level: "info",
            message: `Injected ${count} memories into system prompt`,
            extra: { query: lastUserText.slice(0, 200) },
          },
        });
      } catch (error) {
        await client.app.log({
          body: { service: "mnemosyne", level: "warn", message: `Context injection failed: ${error.message}` },
        });
      }
    },

    // Also inject memory context into the compaction prompt so it survives
    // context-window compaction.
    "experimental.session.compacting": async (input, output) => {
      try {
        const block = await memoryContext(lastUserText || "user preferences and project context");
        if (block) output.context.push(block);
      } catch (error) {
        await client.app.log({
          body: { service: "mnemosyne", level: "warn", message: `Context injection failed: ${error.message}` },
        });
      }
    },
  };
};

export default MnemosynePlugin;
