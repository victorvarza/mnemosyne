// OpenCode V2 plugin tests with a mocked plugin context.
// Run: npm run test:plugin

import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { setupMnemosynePlugin, shouldRunLifecycle, __backgroundTasks } from "../../.opencode/plugins/mnemosyne/index.js";

function fakeMnemo() {
  const dir = mkdtempSync(join(tmpdir(), "mnemo-v2-plugin-"));
  const log = join(dir, "calls.jsonl");
  const bin = join(dir, "mnemo-fake.js");
  writeFileSync(
    bin,
    `#!/usr/bin/env node
import { appendFileSync } from "node:fs";
const args = process.argv.slice(2);
appendFileSync(process.env.MNEMO_TEST_LOG, JSON.stringify(args) + "\\n");
if (args[0] === "context") console.log("## Remembered Context\\n\\n- [semantic|user_stated] I use pytest");
else if (args[0] === "add") console.log("Stored memory abc123...");
else if (args[0] === "search") console.log("Search result");
else if (args[0] === "tools") console.log("Tool output");
else if (args[0] === "assess") console.log("Assessment output");
else if (args[0] === "pentest") console.log("Pentest output");
else if (args[0] === "scan") console.log("Scan output");
else console.log("ok");
`,
  );
  chmodSync(bin, 0o755);
  return { bin, log };
}

function calls(log) {
  return readFileSync(log, "utf8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

async function setup() {
  const fake = fakeMnemo();
  process.env.MNEMO_TEST_LOG = fake.log;
  const tools = new Map();
  const hooks = new Map();
  const ctx = {
    options: { mnemoBin: fake.bin },
    location: { directory: fake.bin.slice(0, fake.bin.lastIndexOf("/")) },
    tool: {
      async transform(callback) {
        callback({
          namespace(namespace) {
            this.lastNamespace = namespace;
          },
          add(tool) {
            tools.set(`${tool.options?.namespace || ""}_${tool.name}`.replace(/^_/, ""), tool);
          },
        });
      },
    },
    session: {
      async hook(name, callback) {
        hooks.set(name, callback);
      },
    },
  };
  await setupMnemosynePlugin(ctx);
  return { fake, tools, hooks };
}

test("V2 plugin registers namespaced Mnemo tools", async () => {
  const { tools } = await setup();

  assert.ok(tools.has("mnemo_remember"));
  assert.ok(tools.has("mnemo_recall"));
  assert.ok(tools.has("mnemo_pentest"));
  assert.ok(tools.has("mnemo_securityToolRun"));
});

test("V2 remember and tool runner execute mnemo CLI", async () => {
  const { fake, tools } = await setup();

  const remember = await tools.get("mnemo_remember").execute({ content: "I prefer pytest" }, {});
  const run = await tools.get("mnemo_securityToolRun").execute(
    {
      toolName: "nmap",
      mode: "docker",
      dockerImage: "ghcr.io/hlesey/mnemo-tools:1.0",
      authorization: "Approved under SEC-123",
      args: "-sV app.example.com",
    },
    {},
  );

  assert.equal(remember.content, "Stored memory abc123...\n");
  assert.equal(run.content, "Tool output\n");
  assert.deepEqual(calls(fake.log), [
    ["add", "--", "I prefer pytest"],
    [
      "tools",
      "run",
      "nmap",
      "--mode",
      "docker",
      "--docker-image",
      "ghcr.io/hlesey/mnemo-tools:1.0",
      "--authorized",
      "Approved under SEC-123",
      "--",
      "-sV",
      "app.example.com",
    ],
  ]);
});

test("V2 prompt hook stores important info and context hook injects memory", async () => {
  const { fake, hooks } = await setup();

  await hooks.get("prompt")({ prompt: { text: "Remember this for later: user prefers pytest" } });
  const event = { system: [] };
  await hooks.get("context")(event);

  assert.deepEqual(calls(fake.log), [
    ["add", "--sanitize", "--", "User mentioned: Remember this for later: user prefers pytest"],
    ["context", "--top-k", "5", "--", "Remember this for later: user prefers pytest"],
  ]);
  assert.equal(event.system.length, 1);
  assert.equal(event.system[0].type, "text");
  assert.match(event.system[0].text, /^## Relevant Context from Memory/);
  assert.match(event.system[0].text, /I use pytest/);
});

test("V2 compaction hook injects generic memory context", async () => {
  const { fake, hooks } = await setup();

  const event = { system: [] };
  await hooks.get("compaction")(event);

  assert.deepEqual(calls(fake.log), [
    ["context", "--top-k", "5", "--", "user preferences and project context"],
  ]);
  assert.equal(event.system.length, 1);
});

test("shouldRunLifecycle debounces by count and interval", () => {
  // Below the capture threshold: never fire.
  assert.equal(
    shouldRunLifecycle({ count: 1, lastRun: 0, now: 10_000, every: 3, minIntervalMs: 1000 }),
    false,
  );
  // Threshold met and interval elapsed: fire.
  assert.equal(
    shouldRunLifecycle({ count: 3, lastRun: 0, now: 10_000, every: 3, minIntervalMs: 1000 }),
    true,
  );
  // Threshold met but too soon since the last run: hold off.
  assert.equal(
    shouldRunLifecycle({ count: 3, lastRun: 9_500, now: 10_000, every: 3, minIntervalMs: 1000 }),
    false,
  );
  // Disabled via every <= 0.
  assert.equal(
    shouldRunLifecycle({ count: 99, lastRun: 0, now: 10_000, every: 0, minIntervalMs: 0 }),
    false,
  );
});

test("V2 auto-capture triggers debounced lifecycle after enough captures", async () => {
  process.env.MNEMO_LIFECYCLE_EVERY = "2";
  process.env.MNEMO_LIFECYCLE_MIN_INTERVAL = "0";
  try {
    const { fake, hooks } = await setup();

    await hooks.get("prompt")({ prompt: { text: "user prefers ruff" } });
    // One capture is below the threshold: no lifecycle yet.
    assert.ok(!calls(fake.log).some((c) => c[0] === "lifecycle"));

    await hooks.get("prompt")({ prompt: { text: "user prefers pytest" } });
    await Promise.allSettled(__backgroundTasks());

    assert.deepEqual(calls(fake.log), [
      ["add", "--sanitize", "--", "User mentioned: user prefers ruff"],
      ["add", "--sanitize", "--", "User mentioned: user prefers pytest"],
      ["lifecycle", "--resolve-conflicts"],
    ]);
  } finally {
    delete process.env.MNEMO_LIFECYCLE_EVERY;
    delete process.env.MNEMO_LIFECYCLE_MIN_INTERVAL;
  }
});

test("V2 auto-capture lifecycle can be disabled", async () => {
  process.env.MNEMO_LIFECYCLE_AUTORUN = "0";
  process.env.MNEMO_LIFECYCLE_EVERY = "1";
  try {
    const { fake, hooks } = await setup();

    await hooks.get("prompt")({ prompt: { text: "user prefers pytest" } });
    await Promise.allSettled(__backgroundTasks());

    assert.ok(!calls(fake.log).some((c) => c[0] === "lifecycle"));
  } finally {
    delete process.env.MNEMO_LIFECYCLE_AUTORUN;
    delete process.env.MNEMO_LIFECYCLE_EVERY;
  }
});
