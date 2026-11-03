// Minimal stand-in for the Stakaba API during e2e runs (never the real sandbox).
// Mobile money creates stay PENDING until a test posts the webhook; card returns a local checkout URL.
import http from "node:http";

const port = Number(process.env.FAKE_STAKABA_PORT ?? 8765);
const webBase = process.env.E2E_WEB_URL ?? "http://localhost:3100";
const payments = [];
let n = 0;

function send(res, status, body) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

http
  .createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const body = raw ? JSON.parse(raw) : {};
      const path = req.url.split("?")[0];
      if (req.method === "GET" && path === "/_e2e/payments") return send(res, 200, payments);
      if (req.method === "POST" && path === "/api/v1/payments/collection") {
        const ref = `FAKEMM${++n}`;
        payments.push({ internalReference: ref, orderId: body.metadata?.orderId, grossAmount: body.grossAmount, method: "mobile_money" });
        return send(res, 200, { internalReference: ref, status: "PENDING" });
      }
      if (req.method === "POST" && path === "/api/v1/payments/card") {
        const ref = `FAKECARD${++n}`;
        payments.push({ internalReference: ref, orderId: body.metadata?.orderId, grossAmount: body.grossAmount, method: "card" });
        return send(res, 200, { internalReference: ref, checkoutUrl: `${webBase}/e2e-fake-card?ref=${ref}` });
      }
      return send(res, 404, { detail: "fake stakaba: unknown route" });
    });
  })
  .listen(port, () => console.log(`fake stakaba on ${port}`));
