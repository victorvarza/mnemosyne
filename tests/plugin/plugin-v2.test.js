// OpenCode V2 plugin tests with a mocked plugin context.
// Run: npm run test:plugin

import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { setupMnemosynePlugin } from "../../.opencode/plugins/mnemosyne/index.js";

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
    ["add", "--", "User mentioned: Remember this for later: user prefers pytest"],
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
