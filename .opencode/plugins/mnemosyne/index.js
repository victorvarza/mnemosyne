import { spawn } from "node:child_process";
import { Plugin } from "@opencode/plugin";

export function extractImportantInfo(text) {
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

// Background tasks (e.g. the debounced lifecycle pass) are fire-and-forget so
// they never block a turn. Tests await these to assert behavior deterministically.
let backgroundTasks = [];
export function __backgroundTasks() {
  return backgroundTasks;
}

function envInt(name, fallback) {
  const raw = process.env[name];
  const value = raw == null ? NaN : Number.parseInt(raw, 10);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

// Pure debounce decision, exported for deterministic unit testing. Fire when at
// least `every` captures have accrued AND at least `minIntervalMs` has passed
// since the last run — so lifecycle never runs on every turn and is rate-limited.
export function shouldRunLifecycle({ count, lastRun, now, every, minIntervalMs }) {
  if (every <= 0) return false;
  if (count < every) return false;
  return now - lastRun >= minIntervalMs;
}

function splitArgs(raw) {
  if (!raw) return [];
  const matches = raw.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g) || [];
  return matches.map((part) => {
    if ((part.startsWith('"') && part.endsWith('"')) || (part.startsWith("'") && part.endsWith("'"))) {
      return part.slice(1, -1);
    }
    return part;
  });
}

function makeRunner(ctx) {
  const directory = ctx.location?.directory || process.cwd();
  const configured = typeof ctx.options?.mnemoBin === "string" ? ctx.options.mnemoBin : "";
  const bin = configured || process.env.MNEMO_BIN || "";
  const base = bin ? [bin] : ["python3", "-m", "mnemo.cli"];

  return function run(args, signal) {
    return new Promise((resolve, reject) => {
      const [command, ...baseArgs] = base;
      const child = spawn(command, [...baseArgs, ...args], {
        cwd: directory,
        env: process.env,
        signal,
        stdio: ["ignore", "pipe", "pipe"],
      });
      let stdout = "";
      let stderr = "";
      child.stdout?.on("data", (chunk) => {
        stdout += chunk.toString();
      });
      child.stderr?.on("data", (chunk) => {
        stderr += chunk.toString();
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0) {
          resolve(stdout);
          return;
        }
        const message = stderr.trim() || stdout.trim() || `mnemo exited with code ${code}`;
        reject(new Error(message));
      });
    });
  };
}

const textResult = (content) => ({ content });

const stringSchema = (description) => ({ type: "string", description });
const optionalStringSchema = (description) => ({ type: "string", description });
const numberSchema = (description) => ({ type: "number", description });

function objectSchema(properties, required = []) {
  return { type: "object", properties, required, additionalProperties: false };
}

function addTool(editor, name, description, input, execute) {
  editor.add({ name, description, input, options: { namespace: "mnemo" }, execute });
}

export async function setupMnemosynePlugin(ctx) {
  const run = makeRunner(ctx);
  let lastUserText = "";
  let cached = { query: null, block: null };

  backgroundTasks = [];
  const lifecycleAutorun = (process.env.MNEMO_LIFECYCLE_AUTORUN ?? "1") !== "0";
  const lifecycleEvery = envInt("MNEMO_LIFECYCLE_EVERY", 3);
  const lifecycleMinIntervalMs = envInt("MNEMO_LIFECYCLE_MIN_INTERVAL", 300) * 1000;
  let captureCount = 0;
  let lastLifecycleRun = 0;

  // Fire-and-forget: run the Phase 3 hygiene pass (conflict resolution) off the
  // turn's critical path, debounced so it never runs per turn. Operates on the
  // session's MNEMO_DB via the shared runner environment.
  const maybeRunLifecycle = () => {
    if (!lifecycleAutorun) return;
    captureCount += 1;
    const now = Date.now();
    if (
      !shouldRunLifecycle({
        count: captureCount,
        lastRun: lastLifecycleRun,
        now,
        every: lifecycleEvery,
        minIntervalMs: lifecycleMinIntervalMs,
      })
    ) {
      return;
    }
    captureCount = 0;
    lastLifecycleRun = now;
    const task = run(["lifecycle", "--resolve-conflicts"]).catch((error) => {
      console.warn(`Mnemosyne lifecycle maintenance failed: ${error.message}`);
    });
    backgroundTasks.push(task);
  };

  const memoryContext = (query, signal) => {
    if (cached.query === query) return cached.block;
    const block = run(["context", "--top-k", "5", "--", query], signal).then((out) => {
      const text = out.trim();
      return text ? `## Relevant Context from Memory\n${text}` : "";
    });
    cached = { query, block };
    block.catch(() => {
      if (cached.block === block) cached = { query: null, block: null };
    });
    return block;
  };

  await ctx.tool.transform((editor) => {
    editor.namespace({
      name: "mnemo",
      description: "Mnemosyne memory and authorized security assessment tools",
    });

    addTool(
      editor,
      "remember",
      "Manually store a memory in Mnemosyne",
      objectSchema({ content: stringSchema("The memory content to store") }, ["content"]),
      async ({ content }, toolCtx) => textResult(await run(["add", "--", content], toolCtx.signal)),
    );

    addTool(
      editor,
      "recall",
      "Manually search memories in Mnemosyne",
      objectSchema({
        query: stringSchema("Search query"),
        topK: numberSchema("Number of results (default 5)"),
      }, ["query"]),
      async ({ query, topK }, toolCtx) => textResult(await run(["search", "--top-k", String(topK ?? 5), "--", query], toolCtx.signal)),
    );

    addTool(
      editor,
      "scan",
      "Scan source code for security vulnerabilities (bandit, semgrep, trivy)",
      objectSchema({ projectPath: optionalStringSchema("Project path (default: .)") }),
      async ({ projectPath }, toolCtx) => textResult(await run(["scan", "--path", projectPath || "."], toolCtx.signal)),
    );

    addTool(
      editor,
      "assessCreate",
      "Create a local authorized security assessment context",
      objectSchema({
        assessmentId: stringSchema("Stable identifier for this assessment"),
        target: stringSchema("Authorized target identifier or URL"),
        authorized: stringSchema("Explicit authorization declaration"),
      }, ["assessmentId", "target", "authorized"]),
      async ({ assessmentId, target, authorized }, toolCtx) => textResult(await run([
        "assess",
        "create",
        assessmentId,
        "--target",
        target,
        "--authorized",
        authorized,
      ], toolCtx.signal)),
    );

    addTool(
      editor,
      "assessRecord",
      "Record an observation or finding under an authorized assessment",
      objectSchema({
        assessmentId: stringSchema("Existing authorized assessment identifier"),
        content: stringSchema("Observation, finding, or outcome"),
        kind: optionalStringSchema("Record kind (default: observation)"),
        severity: optionalStringSchema("Severity (default: info)"),
        evidence: optionalStringSchema("Evidence reference"),
        verification: optionalStringSchema("Verification status (default: unverified)"),
      }, ["assessmentId", "content"]),
      async ({ assessmentId, content, kind, severity, evidence, verification }, toolCtx) => textResult(await run([
        "assess",
        "record",
        assessmentId,
        content,
        "--kind",
        kind || "observation",
        "--severity",
        severity || "info",
        "--evidence",
        evidence || "",
        "--verification",
        verification || "unverified",
      ], toolCtx.signal)),
    );

    addTool(
      editor,
      "pentest",
      "Perform authorized security pentest analysis on source code and a deployed target",
      objectSchema({
        assessmentId: stringSchema("Existing authorized assessment identifier"),
        sourcePath: stringSchema("Path to the source code directory"),
        targetUrl: stringSchema("URL of the deployed target"),
        reportDir: optionalStringSchema("Report output directory (default: .)"),
        maxRequests: numberSchema("Maximum active HTTP requests (default: 100)"),
        allowPrivateIps: optionalStringSchema("Set to 'true' only for authorized labs"),
      }, ["assessmentId", "sourcePath", "targetUrl"]),
      async ({ assessmentId, sourcePath, targetUrl, reportDir, maxRequests, allowPrivateIps }, toolCtx) => {
        const command = [
          "pentest",
          "--assessment",
          assessmentId,
          "--source",
          sourcePath,
          "--target",
          targetUrl,
          "--max-requests",
          String(maxRequests ?? 100),
          "--report-dir",
          reportDir || ".",
        ];
        if (String(allowPrivateIps || "").toLowerCase() === "true") command.push("--allow-private-ips");
        return textResult(await run(command, toolCtx.signal));
      },
    );

    addTool(
      editor,
      "securityToolsList",
      "List Mnemo registered security tools, optionally by category",
      objectSchema({ category: optionalStringSchema("Optional tool category") }),
      async ({ category }, toolCtx) => {
        const command = ["tools", "list"];
        if (category) command.push("--category", category);
        return textResult(await run(command, toolCtx.signal));
      },
    );

    addTool(
      editor,
      "securityToolRun",
      "Run a registered security tool locally or in a Docker/Kali image",
      objectSchema({
        toolName: stringSchema("Registered tool name, e.g. nmap, nuclei, bandit"),
        args: optionalStringSchema("Raw argument string passed to the tool"),
        mode: optionalStringSchema("local or docker (default: docker)"),
        dockerImage: optionalStringSchema("Docker image containing security tools"),
        authorization: optionalStringSchema("Required for active tools"),
        workdir: optionalStringSchema("Directory mounted at /workspace in Docker mode"),
      }, ["toolName"]),
      async (input, toolCtx) => {
        const command = ["tools", "run", input.toolName, "--mode", input.mode || "docker"];
        if (input.dockerImage) command.push("--docker-image", input.dockerImage);
        if (input.authorization) command.push("--authorized", input.authorization);
        if (input.workdir) command.push("--workdir", input.workdir);
        command.push("--", ...splitArgs(input.args || ""));
        return textResult(await run(command, toolCtx.signal));
      },
    );
  });

  await ctx.session.hook("prompt", async (event) => {
    lastUserText = event.prompt?.text || "";
    cached = { query: null, block: null };
    const importantInfo = lastUserText && extractImportantInfo(lastUserText);
    if (!importantInfo) return;
    try {
      await run(["add", "--sanitize", "--", `User mentioned: ${importantInfo}`]);
      maybeRunLifecycle();
    } catch (error) {
      console.warn(`Mnemosyne auto-store failed: ${error.message}`);
    }
  });

  await ctx.session.hook("context", async (event) => {
    if (!lastUserText) return;
    try {
      const block = await memoryContext(lastUserText, event.signal);
      if (block) {
        event.system ??= [];
        event.system.push({ type: "text", text: block });
      }
    } catch (error) {
      console.warn(`Mnemosyne context injection failed: ${error.message}`);
    }
  });

  await ctx.session.hook("compaction", async (event) => {
    try {
      const block = await memoryContext(lastUserText || "user preferences and project context", event.signal);
      if (block) {
        event.system ??= [];
        event.system.push({ type: "text", text: block });
      }
    } catch (error) {
      console.warn(`Mnemosyne compaction context injection failed: ${error.message}`);
    }
  });
}

export const MnemosyneV2Plugin = Plugin.define({
  id: "mnemosyne",
  async setup(ctx) {
    await setupMnemosynePlugin(ctx);
  },
});

export default MnemosyneV2Plugin;
