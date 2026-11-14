import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createAuthServer } from "../src/server.mjs";
import {
  buildAudienceRodit,
  resolveInboundAudience,
} from "../src/lib/rodit.mjs";

describe("buildAudienceRodit", () => {
  it("stamps owner_id and subject URL like OpenClaw inbound", () => {
    const rodit = buildAudienceRodit({
      audience: "owner-abc",
      issuer: "https://agent.example.com",
    });
    assert.equal(rodit.owner_id, "owner-abc");
    assert.equal(rodit.token_id, "a2a-inbound");
    assert.equal(
      rodit.metadata.subjectuniqueidentifier_url,
      "https://agent.example.com"
    );
  });
});

describe("resolveInboundAudience", () => {
  it("falls back to IDENTYCLAW_JWT_* when passport is unavailable", async () => {
    const prevAud = process.env.IDENTYCLAW_JWT_AUDIENCE;
    const prevIss = process.env.IDENTYCLAW_JWT_ISSUER;
    const prevCred = process.env.NEAR_CREDENTIALS_FILE_PATH;
    const prevSrc = process.env.RODIT_NEAR_CREDENTIALS_SOURCE;
    try {
      delete process.env.NEAR_CREDENTIALS_FILE_PATH;
      delete process.env.RODIT_NEAR_CREDENTIALS_SOURCE;
      delete process.env.IDENTYCLAW_ACCOUNT_ID;
      process.env.IDENTYCLAW_JWT_AUDIENCE = "fallback-owner";
      process.env.IDENTYCLAW_JWT_ISSUER = "https://api.example.com/";
      const resolved = await resolveInboundAudience({});
      assert.equal(resolved.audience, "fallback-owner");
      assert.equal(resolved.issuer, "https://api.example.com");
    } finally {
      if (prevAud === undefined) delete process.env.IDENTYCLAW_JWT_AUDIENCE;
      else process.env.IDENTYCLAW_JWT_AUDIENCE = prevAud;
      if (prevIss === undefined) delete process.env.IDENTYCLAW_JWT_ISSUER;
      else process.env.IDENTYCLAW_JWT_ISSUER = prevIss;
      if (prevCred === undefined) delete process.env.NEAR_CREDENTIALS_FILE_PATH;
      else process.env.NEAR_CREDENTIALS_FILE_PATH = prevCred;
      if (prevSrc === undefined) delete process.env.RODIT_NEAR_CREDENTIALS_SOURCE;
      else process.env.RODIT_NEAR_CREDENTIALS_SOURCE = prevSrc;
    }
  });
});

describe("auth sidecar HTTP surface", () => {
  it("serves /health on localhost without credentials", async () => {
    const svc = createAuthServer({ host: "127.0.0.1", port: 0 });
    await new Promise((resolve, reject) => {
      svc.server.listen(0, "127.0.0.1", () => resolve());
      svc.server.once("error", reject);
    });
    const { port } = svc.server.address();
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`);
      assert.equal(res.status, 200);
      const body = await res.json();
      assert.equal(body.ok, true);
      assert.equal(body.service, "hermes-identyclaw-auth");
    } finally {
      await new Promise((resolve) => svc.server.close(resolve));
    }
  });

  it("rejects validate_jwt without token", async () => {
    const svc = createAuthServer({ host: "127.0.0.1", port: 0 });
    await new Promise((resolve, reject) => {
      svc.server.listen(0, "127.0.0.1", () => resolve());
      svc.server.once("error", reject);
    });
    const { port } = svc.server.address();
    try {
      const res = await fetch(`http://127.0.0.1:${port}/v1/validate_jwt`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token: "" }),
      });
      assert.equal(res.status, 401);
      const body = await res.json();
      assert.equal(body.valid, false);
    } finally {
      await new Promise((resolve) => svc.server.close(resolve));
    }
  });

  it("exposes /api/login/timestamp without Passport", async () => {
    const svc = createAuthServer({ host: "127.0.0.1", port: 0 });
    await new Promise((resolve, reject) => {
      svc.server.listen(0, "127.0.0.1", () => resolve());
      svc.server.once("error", reject);
    });
    const { port } = svc.server.address();
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/login/timestamp`);
      assert.equal(res.status, 200);
      const body = await res.json();
      assert.equal(typeof body.timestamp, "number");
      assert.equal(typeof body.timestamp_iso, "string");
    } finally {
      await new Promise((resolve) => svc.server.close(resolve));
    }
  });

  it("returns 503 from /v1/own_passport without credentials", async () => {
    const prevCred = process.env.NEAR_CREDENTIALS_FILE_PATH;
    const prevSrc = process.env.RODIT_NEAR_CREDENTIALS_SOURCE;
    delete process.env.NEAR_CREDENTIALS_FILE_PATH;
    delete process.env.RODIT_NEAR_CREDENTIALS_SOURCE;
    delete process.env.IDENTYCLAW_ACCOUNT_ID;
    const svc = createAuthServer({ host: "127.0.0.1", port: 0 });
    await new Promise((resolve, reject) => {
      svc.server.listen(0, "127.0.0.1", () => resolve());
      svc.server.once("error", reject);
    });
    const { port } = svc.server.address();
    try {
      const res = await fetch(`http://127.0.0.1:${port}/v1/own_passport`);
      assert.equal(res.status, 503);
      const body = await res.json();
      assert.equal(body.ok, false);
    } finally {
      await new Promise((resolve) => svc.server.close(resolve));
      if (prevCred === undefined) delete process.env.NEAR_CREDENTIALS_FILE_PATH;
      else process.env.NEAR_CREDENTIALS_FILE_PATH = prevCred;
      if (prevSrc === undefined) delete process.env.RODIT_NEAR_CREDENTIALS_SOURCE;
      else process.env.RODIT_NEAR_CREDENTIALS_SOURCE = prevSrc;
    }
  });
});

describe("list_sessions never leaks jwt", () => {
  it("session listing shape omits jwt fields", async () => {
    const { listSessions } = await import("../src/lib/session.mjs");
    const out = listSessions();
    assert.equal(out.ok, true);
    assert.ok(Array.isArray(out.sessions));
    for (const s of out.sessions) {
      assert.equal("jwt" in s, false);
      assert.equal("jwt_token" in s, false);
    }
  });
});

describe("logout clears cached jwt", () => {
  it("POSTs /api/logout then removes jwt file and sessions meta", async () => {
    const os = await import("node:os");
    const path = await import("node:path");
    const fs = await import("node:fs");
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "identyclaw-logout-"));
    const prevHome = process.env.IDENTYCLAW_HOME;
    const prevFetch = globalThis.fetch;
    process.env.IDENTYCLAW_HOME = tmp;
    try {
      const { saveJwt, loadJwt, loadSessionsMeta } = await import("../src/lib/paths.mjs");
      const { logout, listSessions } = await import("../src/lib/session.mjs");
      const baseUrl = "https://api.example.test";
      let logoutCalls = 0;
      globalThis.fetch = async (url, opts = {}) => {
        assert.equal(String(url), `${baseUrl}/api/logout`);
        assert.equal(opts.method, "POST");
        assert.equal(opts.headers.authorization, "Bearer fake.jwt.token");
        logoutCalls += 1;
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      };

      saveJwt("fake.jwt.token", baseUrl, { tokenId: "t1", accountid: "acct" });
      assert.ok(loadJwt(baseUrl));
      assert.ok(loadSessionsMeta()[baseUrl]);

      const out = await logout({ baseUrl });
      assert.equal(out.ok, true);
      assert.equal(out.cleared, true);
      assert.equal(out.remote.attempted, true);
      assert.equal(out.remote.ok, true);
      assert.equal(out.remote.status, 200);
      assert.equal(logoutCalls, 1);
      assert.equal(loadJwt(baseUrl), null);
      assert.equal(loadSessionsMeta()[baseUrl], undefined);
      assert.equal(
        listSessions().sessions.some((s) => s.baseUrl === baseUrl),
        false
      );

      const again = await logout({ baseUrl });
      assert.equal(again.ok, true);
      assert.equal(again.cleared, false);
      assert.equal(again.remote.attempted, false);
      assert.equal(logoutCalls, 1);
    } finally {
      globalThis.fetch = prevFetch;
      if (prevHome === undefined) delete process.env.IDENTYCLAW_HOME;
      else process.env.IDENTYCLAW_HOME = prevHome;
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });
});
