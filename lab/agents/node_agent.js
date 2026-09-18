// WAVE-1 AGENT #2 -- Node.js external agent (Tier ceiling: T2).
// Runtime diversity: a different HTTP stack, JSON parser and HMAC implementation
// than the Python agent. Requires nothing from ACT (no ../backend path, no `app`).
// Same ACT-HMAC-SHA256 protocol; same tier ladder: T1 read-only, T2 one governed write.
"use strict";
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");

const SCHEME = "ACT-HMAC-SHA256";

function unwrap(obj) {
  return obj && obj.success === true && "data" in obj ? obj.data : obj;
}

function request(method, url, headers, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname + u.search, method, headers }, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        let parsed = {};
        try { parsed = data ? JSON.parse(data) : {}; } catch (e) { parsed = { raw: data }; }
        resolve([res.statusCode, unwrap(parsed)]);
      });
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

async function signedCall(base, path, keyId, secret, payload) {
  const body = JSON.stringify(payload);
  const ts = String(Math.floor(Date.now() / 1000));
  const nonce = crypto.randomUUID().replace(/-/g, "");
  const digest = crypto.createHash("sha256").update(body).digest("hex");
  const toSign = [SCHEME, "POST", path, ts, nonce, digest].join("\n");
  const sig = crypto.createHmac("sha256", secret).update(toSign).digest("hex");
  return request("POST", base + path, {
    "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body),
    "X-ACT-Key-Id": keyId, "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig,
  }, body);
}

(async () => {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const out = { agent: "node", tier: cfg.tier || 2, canary_present_in_config: cfg.canary.startsWith("ACTLAB-CANARY") };
  out.t1_object_store = (await request("GET", cfg.object_store + "/objects", {}))[0];
  if ((cfg.tier || 2) >= 2 && cfg.key_id) {
    out.t2_allowed = await signedCall(cfg.act_base, "/api/v1/bridge/capability", cfg.key_id, cfg.secret,
      { capability: "http_tool.invoke", target_ref: cfg.allowed_tool, params: { body: { from: "lab-node-agent" } } });
    out.t2_forbidden = await signedCall(cfg.act_base, "/api/v1/bridge/capability", cfg.key_id, cfg.secret,
      { capability: "http_tool.invoke", target_ref: cfg.forbidden_tool });
  }
  process.stdout.write(JSON.stringify(out) + "\n");
})().catch((e) => { console.error(e); process.exit(1); });
