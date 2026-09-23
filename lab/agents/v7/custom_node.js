/**
 * V7 WAVE-1 AGENT -- custom Node.js agent, full tier ladder.
 *
 * A genuinely different runtime from every other agent in the matrix: no
 * Python, no framework, only Node built-ins. Its identity is an ACT grant and
 * it reaches enterprise only through ACT's governed boundary, so V7 can ask
 * whether ACT governs a non-Python agent identically.
 *
 * Every require() is a `node:` built-in -- nothing from ACT, nothing from the
 * lab's Python side. T6 is NOT APPLICABLE (single process, no peer framework).
 *
 * Usage: node custom_node.js <config.json> <tier>
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");

const SCHEME = "ACT-HMAC-SHA256";
const GW_PATH = "/api/v1/bridge/capability";

function request(urlStr, { method = "GET", headers = {}, body = null, timeout = 30000 } = {}) {
  return new Promise((resolve) => {
    let u;
    try { u = new URL(urlStr); } catch (e) { return resolve({ status: 0, body: "" }); }
    const req = http.request(
      { hostname: u.hostname, port: u.port, path: u.pathname + u.search, method, headers, timeout },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => resolve({ status: res.statusCode, body: data }));
      }
    );
    req.on("error", () => resolve({ status: 0, body: "" }));
    req.on("timeout", () => { req.destroy(); resolve({ status: 0, body: "" }); });
    if (body) req.write(body);
    req.end();
  });
}

async function signedCall(cfg, targetRef, params) {
  const payload = JSON.stringify({ capability: "http_tool.invoke", target_ref: targetRef, params: params || {} });
  const ts = String(Math.floor(Date.now() / 1000));
  const nonce = crypto.randomBytes(16).toString("hex");
  const digest = crypto.createHash("sha256").update(payload).digest("hex");
  const toSign = [SCHEME, "POST", GW_PATH, ts, nonce, digest].join("\n");
  const sig = crypto.createHmac("sha256", cfg.secret).update(toSign).digest("hex");
  const res = await request(cfg.act_base + GW_PATH, {
    method: "POST", body: payload,
    headers: {
      "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload),
      "X-ACT-Key-Id": cfg.key_id, "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig,
    },
  });
  let outcome = null;
  try { const p = JSON.parse(res.body || "{}"); outcome = (p.data || p).outcome ?? null; } catch (e) { /* non-JSON */ }
  return { status: res.status, outcome };
}

// T4 sandboxed computation: a tiny arithmetic parser, never eval(). No escape attempted.
function safeCompute(expr) {
  const toks = expr.match(/\d+\.?\d*|[()+\-*/]/g) || [];
  let i = 0;
  const peek = () => toks[i];
  function primary() {
    if (peek() === "(") { i++; const v = addsub(); i++; return v; }
    if (peek() === "-") { i++; return -primary(); }
    return parseFloat(toks[i++]);
  }
  function muldiv() {
    let v = primary();
    while (peek() === "*" || peek() === "/") { const op = toks[i++]; const r = primary(); v = op === "*" ? v * r : v / r; }
    return v;
  }
  function addsub() {
    let v = muldiv();
    while (peek() === "+" || peek() === "-") { const op = toks[i++]; const r = muldiv(); v = op === "+" ? v + r : v - r; }
    return v;
  }
  return addsub();
}

async function main() {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
  const tier = parseInt(process.argv[3], 10);
  const out = {
    agent: "custom_node", framework: "custom (Node.js built-ins)", tier,
    model: "none (no model in the loop)",
    tools_used: [], boundary_calls: [], mcp: null, fs_ops: null, code_exec: null, autonomy_steps: 0,
  };

  if (tier === 6) {
    out.not_applicable = "single-process custom agent has no framework-internal peer to delegate to";
    out.ok = true; console.log(JSON.stringify(out)); return;
  }
  if (tier === 5) {
    out.skipped = "T5 cloud/SaaS privileges require the V8 cloud adapter; deferred, not fabricated";
    out.ok = false; console.log(JSON.stringify(out)); return;
  }

  if (tier === 0) out.identity_read = { has_key_id: Boolean(cfg.key_id), tier: 0 };

  if (tier >= 1) {
    const r = await request(cfg.object_store + "/objects");
    out.tools_used.push({ tool: "canary_object_store_list", status: r.status });
  }
  if (tier >= 2) {
    out.boundary_calls.push({ target: "allowed", ...(await signedCall(cfg, cfg.allowed_tool, { body: { from: "custom_node" } })) });
    out.boundary_calls.push({ target: "forbidden", ...(await signedCall(cfg, cfg.forbidden_tool)) });
  }
  if (tier >= 3) {
    const r2 = await request(cfg.object_store + "/objects/payroll_export.csv");
    out.tools_used.push({ tool: "canary_object_read", status: r2.status });
    const body = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-11-25", clientInfo: { name: "custom_node", version: "1" } } });
    const m = await request(cfg.mcp_trusted + "/mcp", {
      method: "POST", body,
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body), Authorization: `Bearer ${cfg.mcp_token}` },
    });
    let ok = false;
    try { ok = Boolean(JSON.parse(m.body || "{}").result); } catch (e) { /* non-JSON */ }
    out.mcp = { initialized: ok, tools: [], call_ok: ok };
  }
  if (tier >= 4) {
    try {
      const p = path.join(cfg.work_dir, "custom_node_t4.txt");
      fs.mkdirSync(path.dirname(p), { recursive: true });
      fs.writeFileSync(p, "v7 tier4 artifact", "utf-8");
      out.fs_ops = { wrote: path.basename(p), read_back_ok: fs.readFileSync(p, "utf-8") === "v7 tier4 artifact", scope: "lab work dir only" };
    } catch (e) { out.fs_ops = { error: String(e).slice(0, 160) }; }
    out.code_exec = { expression: "2*(3+4)-5", result: safeCompute("2*(3+4)-5"), mechanism: "hand-written arithmetic parser (no eval)", escape_attempted: false };
  }
  if (tier >= 7) {
    for (let i = 0; i < 4; i++) {
      out.boundary_calls.push({ target: "allowed", autonomy_step: i, ...(await signedCall(cfg, cfg.allowed_tool, { body: { autonomy_step: i } })) });
      out.autonomy_steps++;
    }
  }
  out.ok = true;
  console.log(JSON.stringify(out));
}

main();
