const MAX_HISTORY_CONTENT = 4_000;
const MAX_TOOL_DETAIL = 2_000;

function textNode(text) {
  return { type: "text", text };
}

function safeLink(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
  } catch {
    return "";
  }
}

export function parseInline(source) {
  const nodes = [];
  let plain = "";
  const flush = () => {
    if (plain) nodes.push(textNode(plain));
    plain = "";
  };
  for (let index = 0; index < source.length;) {
    if (source[index] === "\n") {
      flush();
      nodes.push({ type: "break" });
      index += 1;
      continue;
    }
    if (source.startsWith("**", index)) {
      const end = source.indexOf("**", index + 2);
      if (end > index + 2) {
        flush();
        nodes.push({ type: "strong", children: [textNode(source.slice(index + 2, end))] });
        index = end + 2;
        continue;
      }
    }
    if (source[index] === "`") {
      const end = source.indexOf("`", index + 1);
      if (end > index + 1) {
        flush();
        nodes.push({ type: "code", text: source.slice(index + 1, end) });
        index = end + 1;
        continue;
      }
    }
    if (source[index] === "[") {
      const labelEnd = source.indexOf("](", index + 1);
      const hrefEnd = labelEnd < 0 ? -1 : source.indexOf(")", labelEnd + 2);
      if (labelEnd > index + 1 && hrefEnd > labelEnd + 2) {
        const label = source.slice(index + 1, labelEnd);
        const rawHref = source.slice(labelEnd + 2, hrefEnd);
        const href = safeLink(rawHref);
        flush();
        if (href) nodes.push({ type: "link", href, children: [textNode(label)] });
        else nodes.push(textNode(source.slice(index, hrefEnd + 1)));
        index = hrefEnd + 1;
        continue;
      }
    }
    if (source[index] === "*" && source[index + 1] !== "*") {
      const end = source.indexOf("*", index + 1);
      if (end > index + 1) {
        flush();
        nodes.push({ type: "emphasis", children: [textNode(source.slice(index + 1, end))] });
        index = end + 1;
        continue;
      }
    }
    plain += source[index];
    index += 1;
  }
  flush();
  return nodes;
}

function startsBlock(line) {
  return /^(?:#{1,6}\s|```|\s*[-+*]\s+|\s*\d+[.)]\s+|>\s?)/.test(line);
}

export function parseMarkdown(markdown) {
  const lines = String(markdown || "").replaceAll("\r\n", "\n").split("\n");
  const blocks = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const language = line.slice(3).trim().slice(0, 32);
      const code = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ type: "code_block", language, text: code.join("\n") });
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, children: parseInline(heading[2]) });
      index += 1;
      continue;
    }
    const unordered = /^\s*[-+*]\s+(.+)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      const isOrdered = Boolean(ordered);
      const items = [];
      while (index < lines.length) {
        const match = isOrdered
          ? /^\s*\d+[.)]\s+(.+)$/.exec(lines[index])
          : /^\s*[-+*]\s+(.+)$/.exec(lines[index]);
        if (!match) break;
        items.push(parseInline(match[1]));
        index += 1;
      }
      blocks.push({ type: "list", ordered: isOrdered, items });
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", children: parseInline(quote.join("\n")) });
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", children: parseInline(paragraph.join("\n")) });
  }
  return blocks;
}

function appendInline(parent, nodes) {
  for (const node of nodes) {
    if (node.type === "text") parent.append(document.createTextNode(node.text));
    else if (node.type === "break") parent.append(document.createElement("br"));
    else if (node.type === "code") {
      const code = document.createElement("code");
      code.textContent = node.text;
      parent.append(code);
    } else if (["strong", "emphasis", "link"].includes(node.type)) {
      const element = document.createElement(
        node.type === "emphasis" ? "em" : node.type === "link" ? "a" : "strong",
      );
      if (node.type === "link") {
        element.href = node.href;
        element.target = "_blank";
        element.rel = "noopener noreferrer";
      }
      appendInline(element, node.children);
      parent.append(element);
    }
  }
}

export function renderMarkdown(parent, markdown) {
  for (const block of parseMarkdown(markdown)) {
    if (block.type === "code_block") {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (block.language) code.dataset.language = block.language;
      code.textContent = block.text;
      pre.append(code);
      parent.append(pre);
      continue;
    }
    if (block.type === "list") {
      const list = document.createElement(block.ordered ? "ol" : "ul");
      for (const children of block.items) {
        const item = document.createElement("li");
        appendInline(item, children);
        list.append(item);
      }
      parent.append(list);
      continue;
    }
    const element =
      block.type === "heading"
        ? document.createElement(`h${Math.min(6, block.level + 1)}`)
        : document.createElement(block.type === "quote" ? "blockquote" : "p");
    appendInline(element, block.children);
    parent.append(element);
  }
}

function parseArguments(raw) {
  if (raw && typeof raw === "object") return raw;
  if (typeof raw !== "string" || !raw.trim()) return {};
  try { return JSON.parse(raw); } catch { return {}; }
}

export function toolDisplay(name, rawInput) {
  const normalized = String(name || "").trim();
  if (normalized === "load_skill") return "Load operating skill";
  if (normalized === "relay__ui_inspect") return "Inspect desktop";
  if (normalized === "relay__computer") {
    const action = parseArguments(rawInput).action;
    return ({
      screenshot: "Capture desktop",
      cursor_position: "Locate pointer",
      mouse_move: "Move pointer",
      click: "Click desktop",
      left_click: "Click desktop",
      right_click: "Open context menu",
      middle_click: "Middle-click desktop",
      double_click: "Double-click desktop",
      triple_click: "Triple-click desktop",
      left_click_drag: "Drag on desktop",
      left_mouse_down: "Hold mouse button",
      left_mouse_up: "Release mouse button",
      type: "Type text",
      key: "Press keys",
      hold_key: "Hold key",
      scroll: "Scroll desktop",
      wait: "Wait for desktop",
      release_control: "Release desktop control",
    })[action] || "Control desktop";
  }
  if (normalized === "record_screen") {
    return ({
      START_RECORDING: "Start screen recording",
      SAVE_RECORDING: "Save screen recording",
      DISCARD_RECORDING: "Discard screen recording",
    })[parseArguments(rawInput).mode] || "Record desktop";
  }
  if (normalized === "terminal") {
    return ({
      list: "List terminal sessions",
      create: "Create terminal session",
      capture: "Read terminal output",
      send: "Send terminal input",
      destroy: "Close terminal session",
    })[parseArguments(rawInput).action] || "Operate terminal";
  }
  const leaf = normalized.includes("__") ? normalized.split("__").at(-1) : normalized;
  if (normalized.startsWith("playwright__")) {
    return ({
      browser_navigate: "Open browser page",
      browser_snapshot: "Inspect browser DOM",
      browser_click: "Click browser element",
      browser_type: "Type in browser",
      browser_press_key: "Press browser key",
      browser_console_messages: "Read browser console",
      browser_network_requests: "Inspect browser network",
      browser_take_screenshot: "Capture browser page",
      browser_evaluate: "Evaluate browser page",
      browser_run_code: "Run browser debug code",
    })[leaf] || "Inspect browser";
  }
  return leaf
    ? leaf.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase())
    : "Agent tool";
}

function toolResultText(content) {
  if (typeof content === "string") return content.slice(0, MAX_TOOL_DETAIL);
  if (!Array.isArray(content)) return "";
  return content
    .map((item) => item?.content?.text || item?.content?.content?.text || item?.text || "")
    .filter(Boolean)
    .join("\n")
    .slice(0, MAX_TOOL_DETAIL);
}

function upsertTool(items, payload, updateOnly = false) {
  const id = String(payload.toolCallId || payload.tool_call_id || "").trim();
  if (!id) return items;
  const existingIndex = items.findIndex((item) => item.type === "tool" && item.id === id);
  const existing = existingIndex >= 0 ? items[existingIndex] : null;
  const rawName = payload.name || payload.title || existing?.rawName || "";
  const rawInput = payload.input ?? payload.arguments ?? existing?.rawInput ?? "";
  const detail = toolResultText(payload.content) || existing?.detail || "";
  const next = {
    type: "tool",
    id,
    rawName,
    rawInput,
    title: existing?.title || toolDisplay(rawName, rawInput),
    status: payload.status || existing?.status || (updateOnly ? "in_progress" : "pending"),
    detail,
  };
  if (existingIndex < 0) return [...items, next];
  const copy = items.slice();
  copy[existingIndex] = next;
  return copy;
}

function appendDelta(items, role, content) {
  if (!content) return items;
  const last = items.at(-1);
  if (last?.type === "message" && last.role === role && last.streaming) {
    return [...items.slice(0, -1), { ...last, content: last.content + content }];
  }
  return [...items, { type: "message", role, content, streaming: true }];
}

export function applyAgentEvent(items, name, rawPayload) {
  if (rawPayload === "[DONE]") return items.map((item) => ({ ...item, streaming: false }));
  const payload = typeof rawPayload === "string" ? JSON.parse(rawPayload) : rawPayload;
  if (name === "tool_call") return upsertTool(items, payload);
  if (name === "tool_call_update") return upsertTool(items, payload, true);
  const delta = payload?.choices?.[0]?.delta || {};
  if (typeof delta.reasoning_content === "string") {
    return appendDelta(items, "reasoning", delta.reasoning_content);
  }
  if (typeof delta.content === "string") return appendDelta(items, "assistant", delta.content);
  return items;
}

export function parseSSEText(raw) {
  const events = [];
  let name = "message";
  let data = [];
  const dispatch = () => {
    if (data.length) events.push({ name, data: data.join("\n") });
    name = "message";
    data = [];
  };
  for (const line of String(raw || "").split(/\r?\n/)) {
    if (!line) dispatch();
    else if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  dispatch();
  return events;
}

export function normalizeHistory(messages) {
  let items = [];
  for (const message of Array.isArray(messages) ? messages.slice(-50) : []) {
    if (!message || typeof message !== "object") continue;
    if (message.role === "assistant" && Array.isArray(message.tool_calls)) {
      for (const call of message.tool_calls) {
        items = upsertTool(items, {
          toolCallId: call.id,
          name: call.name || call.function?.name,
          input: call.input ?? call.function?.arguments,
          status: "pending",
        });
      }
    }
    if (message.role === "tool") {
      const content = typeof message.content === "string" ? message.content : "";
      items = upsertTool(items, {
        toolCallId: message.tool_call_id,
        status: /^\s*error:/i.test(content) ? "failed" : "completed",
        content,
      }, true);
      continue;
    }
    if (!['user', 'assistant'].includes(message.role) || typeof message.content !== "string") continue;
    if (!message.content.trim()) continue;
    items.push({
      type: "message",
      role: message.role,
      content: message.content.slice(0, MAX_HISTORY_CONTENT),
      streaming: false,
    });
  }
  return items;
}
