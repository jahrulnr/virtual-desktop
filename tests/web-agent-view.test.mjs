import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  applyAgentEvent,
  normalizeHistory,
  parseMarkdown,
  parseSSEText,
  renderMarkdown,
  toolDisplay,
} from "../web/agent-view.mjs";

test("Markdown is parsed into safe structural nodes without executable HTML", () => {
  const blocks = parseMarkdown([
    "# Result",
    "",
    "Use **Chromium** and `Ctrl+L`.",
    "",
    "- Open the browser",
    "- Visit [safe](https://example.com) and [unsafe](javascript:alert(1))",
    "",
    "<img src=x onerror=alert(1)>",
  ].join("\n"));

  assert.equal(blocks[0].type, "heading");
  assert.equal(blocks[0].level, 1);
  assert.equal(blocks[1].children.some((node) => node.type === "strong"), true);
  assert.equal(blocks[1].children.some((node) => node.type === "code"), true);
  assert.equal(blocks[2].type, "list");
  assert.equal(JSON.stringify(blocks).includes('"href":"https://example.com/"'), true);
  assert.equal(JSON.stringify(blocks).includes('"href":"javascript:'), false);
  assert.equal(blocks.at(-1).type, "paragraph");
  assert.equal(blocks.at(-1).children[0].text, "<img src=x onerror=alert(1)>");
});

test("renderMarkdown is exported for the browser shell", () => {
  assert.equal(typeof renderMarkdown, "function");
});

test("persisted Coddy history skips empty assistant shells and reconstructs tool calls", () => {
  const items = normalizeHistory([
    { role: "user", content: "Open YouTube" },
    {
      role: "assistant",
      content: "",
      tool_calls: [{ id: "load", type: "function", function: { name: "load_skill", arguments: "{}" } }],
    },
    { role: "tool", tool_call_id: "load", content: "Relay OS Operator loaded." },
    {
      role: "assistant",
      content: "",
      tool_calls: [{
        id: "click",
        type: "function",
        function: { name: "relay__computer", arguments: '{"action":"click"}' },
      }],
    },
    { role: "tool", tool_call_id: "click", content: "error: coordinate must be an array" },
    { role: "assistant", content: "We need to **fix** the arguments." },
  ]);

  assert.deepEqual(items.map((item) => `${item.type}:${item.role || item.status}`), [
    "message:user",
    "tool:completed",
    "tool:failed",
    "message:assistant",
  ]);
  assert.equal(items.some((item) => item.type === "message" && item.content === ""), false);
  assert.equal(items[1].title, "Load operating skill");
  assert.equal(items[2].title, "Click desktop");
  assert.match(items[2].detail, /coordinate must be an array/);
});

test("the captured OpenRouter free stream keeps one card per tool and chronological final text", async () => {
  const raw = await readFile(new URL("./fixtures/openrouter-free-medium.sse", import.meta.url), "utf8");
  let items = [];
  for (const event of parseSSEText(raw)) {
    items = applyAgentEvent(items, event.name, event.data);
  }

  assert.deepEqual(items.map((item) => item.type === "tool" ? `tool:${item.id}:${item.status}` : `${item.type}:${item.role}`), [
    "tool:call-load-skill:completed",
    "tool:call-inspect:completed",
    "tool:call-click:failed",
    "message:assistant",
  ]);
  assert.match(items.at(-1).content, /\*\*coordinate\*\*/);
  assert.equal(items.filter((item) => item.type === "tool").length, 3);
});

test("tool names are presented as user-facing actions", () => {
  assert.equal(toolDisplay("load_skill", "{}"), "Load operating skill");
  assert.equal(toolDisplay("relay__ui_inspect", "{}"), "Inspect desktop");
  assert.equal(toolDisplay("relay__computer", '{"action":"left_click"}'), "Click desktop");
  assert.equal(toolDisplay("relay__computer", '{"action":"screenshot"}'), "Capture desktop");
});
