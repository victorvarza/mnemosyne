// Hook-level tests for opencode-plugin.js with a stubbed Bun `$` and client.
// Run: npm run test:plugin  (or: bun test tests/plugin)

import assert from "node:assert/strict";
import { test } from "node:test";

import { MnemosynePlugin } from "../../opencode-plugin.js";

// Mimics Bun's ShellPromise: awaiting resolves to Buffers, `.text()` to a string.
function fakeShell({ stdout = "", fail = false } = {}) {
  const calls = [];
  const $ = (strings, ...values) => {
    const call = { strings: [...strings], args: values.flat(), cwd: null };
    calls.push(call);
    const result = fail
      ? Promise.reject(new Error("mnemo exited with code 1"))
      : Promise.resolve({ stdout: Buffer.from(stdout), stderr: Buffer.alloc(0), exitCode: 0 });
    result.catch(() => {});
    const shell = {
      cwd(dir) {
        call.cwd = dir;
        return shell;
      },
      text: () => result.then((r) => r.stdout.toString()),
      then: (onOk, onErr) => result.then(onOk, onErr),
    };
    return shell;
  };
  return { $, calls };
}

function fakeClient() {
  const logs = [];
  return {
    logs,
    app: { log: async ({ body }) => logs.push(body) },
    session: { message: async () => ({ data: { parts: [] } }) },
  };
}

async function setup(shellOptions) {
  const { $, calls } = fakeShell(shellOptions);
  const client = fakeClient();
  const hooks = await MnemosynePlugin({ project: {}, client, $, directory: "/repo", worktree: "/repo" });
  return { hooks, calls, client };
}

const userTurn = (text) => ({ parts: [{ type: "text", text }] });

test("system.transform injects memories for the latest user message", async () => {
  const { hooks, calls } = await setup({
    stdout: "## Remembered Context\n\n- [semantic|user_stated] I use VS Code\n",
  });

  await hooks["chat.message"]({}, userTurn("Which editor do I use?"));
  const output = { system: ["base system prompt"] };
  await hooks["experimental.chat.system.transform"]({}, output);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].cwd, "/repo");
  assert.deepEqual(calls[0].args, ["context", "--top-k", "5", "--", "Which editor do I use?"]);
  assert.equal(output.system.length, 2);
  assert.match(output.system[1], /^## Relevant Context from Memory\n/);
  assert.match(output.system[1], /I use VS Code/);
});

test("system.transform logs how many memories were injected", async () => {
  const { hooks, client } = await setup({
    stdout: "## Remembered Context\n\n- [semantic|user_stated] a\n- [semantic|user_stated] b\n",
  });
  await hooks["chat.message"]({}, userTurn("q"));
  await hooks["experimental.chat.system.transform"]({}, { system: [] });

  assert.ok(client.logs.some((l) => l.level === "info" && l.message === "Injected 2 memories into system prompt"));
});

test("MNEMO_BIN replaces `python3 -m mnemo.cli` as the command", async () => {
  process.env.MNEMO_BIN = "/opt/mnemo/.venv/bin/mnemo";
  try {
    const { hooks, calls } = await setup({ stdout: "" });
    await hooks.tool.remember.execute({ content: "x" });
    assert.deepEqual(calls[0].args, ["/opt/mnemo/.venv/bin/mnemo", "add", "--", "x"]);
  } finally {
    delete process.env.MNEMO_BIN;
  }
});

test("user text starting with a dash is passed after `--`, not as a flag", async () => {
  const { hooks, calls } = await setup({ stdout: "" });
  await hooks["chat.message"]({}, userTurn("--help me"));
  await hooks["experimental.chat.system.transform"]({}, { system: [] });

  const args = calls[0].args;
  assert.equal(args.at(-1), "--help me");
  assert.equal(args.at(-2), "--");
});

test("one retrieval per user message, even when the system prompt is transformed twice", async () => {
  const { hooks, calls } = await setup({ stdout: "- [semantic|user_stated] a\n" });
  await hooks["chat.message"]({}, userTurn("first question"));
  const title = { system: [] };
  const reply = { system: [] };
  await Promise.all([
    hooks["experimental.chat.system.transform"]({}, title),
    hooks["experimental.chat.system.transform"]({}, reply),
  ]);
  assert.equal(calls.length, 1);
  assert.equal(title.system.length, 1);
  assert.equal(reply.system.length, 1);

  await hooks["chat.message"]({}, userTurn("second question"));
  await hooks["experimental.chat.system.transform"]({}, { system: [] });
  assert.equal(calls.length, 2);
  assert.equal(calls[1].args.at(-1), "second question");
});

test("system.transform is a no-op before any user message", async () => {
  const { hooks, calls } = await setup({ stdout: "something" });
  const output = { system: ["base"] };
  await hooks["experimental.chat.system.transform"]({}, output);

  assert.equal(calls.length, 0);
  assert.deepEqual(output.system, ["base"]);
});

test("system.transform adds nothing when no memory is relevant", async () => {
  const { hooks } = await setup({ stdout: "  \n" });
  await hooks["chat.message"]({}, userTurn("Tell me a joke"));
  const output = { system: ["base"] };
  await hooks["experimental.chat.system.transform"]({}, output);

  assert.deepEqual(output.system, ["base"]);
});

test("a failing mnemo call is logged and does not break the turn", async () => {
  const { hooks, client } = await setup({ fail: true });
  await hooks["chat.message"]({}, userTurn("Which editor do I use?"));
  const output = { system: ["base"] };
  await hooks["experimental.chat.system.transform"]({}, output);

  assert.deepEqual(output.system, ["base"]);
  assert.ok(client.logs.some((l) => l.level === "warn" && /Context injection failed/.test(l.message)));
});

test("compaction injects context, falling back to a generic query", async () => {
  const { hooks, calls } = await setup({ stdout: "- [semantic|user_stated] I live in Cluj\n" });
  const output = { context: [] };
  await hooks["experimental.session.compacting"]({}, output);

  assert.equal(calls[0].args.at(-1), "user preferences and project context");
  assert.equal(output.context.length, 1);
  assert.match(output.context[0], /I live in Cluj/);
});

test("tools return the CLI output as a string", async () => {
  const { hooks, calls } = await setup({ stdout: "Stored memory abc123...\n" });
  const out = await hooks.tool.remember.execute({ content: "I prefer pytest" });

  assert.equal(typeof out, "string");
  assert.equal(out, "Stored memory abc123...\n");
  assert.deepEqual(calls[0].args, ["add", "--", "I prefer pytest"]);
});

test("pentest tool uses an authorized assessment id", async () => {
  const { hooks, calls } = await setup({ stdout: "report saved\n" });
  await hooks.tool.pentest.execute({
    assessmentId: "web-lab",
    sourcePath: "./app",
    targetUrl: "https://app.example.com",
    maxRequests: 25,
    reportDir: "reports",
  });

  assert.deepEqual(calls[0].args, [
    "pentest",
    "--assessment",
    "web-lab",
    "--source",
    "./app",
    "--target",
    "https://app.example.com",
    "--max-requests",
    "25",
    "--report-dir",
    "reports",
  ]);
});

test("assessment and security tool wrappers call mnemo CLI", async () => {
  const { hooks, calls } = await setup({ stdout: "ok\n" });

  await hooks.tool.assessCreate.execute({
    assessmentId: "web-lab",
    target: "https://app.example.com",
    authorized: "Approved under SEC-123",
  });
  await hooks.tool.securityToolsList.execute({ category: "web-scan" });
  await hooks.tool.securityToolRun.execute({
    toolName: "nmap",
    mode: "docker",
    dockerImage: "shannon-tools",
    authorization: "Approved under SEC-123",
    args: "-sV app.example.com",
  });

  assert.deepEqual(calls[0].args, [
    "assess",
    "create",
    "web-lab",
    "--target",
    "https://app.example.com",
    "--authorized",
    "Approved under SEC-123",
  ]);
  assert.deepEqual(calls[1].args, ["tools", "list", "--category", "web-scan"]);
  assert.deepEqual(calls[2].args, [
    "tools",
    "run",
    "nmap",
    "--mode",
    "docker",
    "--docker-image",
    "shannon-tools",
    "--authorized",
    "Approved under SEC-123",
    "--",
    "-sV",
    "app.example.com",
  ]);
});
