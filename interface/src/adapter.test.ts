// interface/src/adapter.test.ts
// Contract for the M1/M3/M5 adapter layer.
// If this passes, dropping in the real FastAPI client is one file, not one screen.

import { describe, it, expect, beforeEach } from "vitest";
import { createAdapter } from "./adapter";
import type { AdapterConfig } from "./adapter";
import { fixture } from "./fixtures/dupont-v-acme";

// The adapter is explicitly configured with either a backend URL or null.
const fixtureConfig: AdapterConfig = { backend: null };
const liveConfig: AdapterConfig = { backend: { baseUrl: "http://localhost:8000" } };

describe("fixture adapter", () => {
  let adapter: ReturnType<typeof createAdapter>;

  beforeEach(() => {
    adapter = createAdapter(fixtureConfig);
  });

  // ---------------------------------------------------------------------------
  // 1. Fixture mode returns the fixture, unchanged
  // ---------------------------------------------------------------------------

  it("returns the seeded case when no backend is configured", async () => {
    const result = await adapter.cases.get(fixture.case.id);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.key).toBe("CASE-2024-018");
    expect(result.value.title).toBe("DUPONT v. ACME");
    expect(result.value.holdCount).toBe(1);
  });

  it("returns all six evidence items for the seeded case", async () => {
    const result = await adapter.evidence.list(fixture.case.id);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toHaveLength(6);
    expect(result.value.map((e) => e.id).sort()).toEqual(
      ["E-1042", "E-1043", "E-1044", "E-1045", "E-1046", "E-1047"],
    );
  });

  it("keeps the quarantined item quarantined with a named reason", async () => {
    const result = await adapter.evidence.get("E-1044");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.status).toBe("quarantined");
    expect(result.value.quarantinedReason).toBe("scan_unsupported_variant");
    // Leaf token only. If it has a dot, the drift is back.
    expect(result.value.quarantinedReason).not.toContain(".");
  });

  it("keeps the integrity hold item on hold with a named reason", async () => {
    const result = await adapter.evidence.get("E-1047");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.status).toBe("integrity_hold");
    expect(result.value.holdReason).toBe("hash_mismatch_at_readback");
  });

  // ---------------------------------------------------------------------------
  // 2. Error keys surface as named failing steps, not generic strings
  // ---------------------------------------------------------------------------

  it("returns the failing step for E-1047 as a named key", async () => {
    const result = await adapter.evidence.verify("E-1047");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.result).toBe("fail");
    expect(result.value.failingStep).toBe("hash_mismatch_at_readback");
    // The failing step is a leaf token the UI resolves via `reason.${step}`.
    expect(result.value.failingStep).not.toMatch(/^reason\./);
    expect(result.value.failingStep).not.toContain(".");
  });

  it("returns every verification step with a discrete result", async () => {
    const result = await adapter.evidence.verify("E-1047");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const ids = result.value.steps.map((s) => s.id).sort();
    expect(ids).toEqual(["anchor", "chain", "hash", "signature"]);
    const results = result.value.steps.map((s) => s.result);
    expect(results).toContain("fail");
    expect(results).toContain("pass");
    // No step may be "unknown" or missing a result.
    for (const r of results) expect(["pass", "fail"]).toContain(r);
  });

  it("returns CASE_KEY_TAKEN as a named error key, not a prose string", async () => {
    const result = await adapter.cases.create({
      key: fixture.case.key, // already in use
      title: "Duplicate",
      jurisdiction: "QC",
      matterType: "labour",
      timezone: "America/Montreal",
      description: "",
      memberIds: [],
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toBe("CASE_KEY_TAKEN");
    // Error keys are uppercase identifiers. They resolve via `error.${key}`.
    expect(result.error).toMatch(/^[A-Z][A-Z0-9_]+$/);
  });

  it("returns GATE_FAILED with the failing gate and item named", async () => {
    const result = await adapter.exports.preview(fixture.case.id, "signed_audit_package");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const barreau = result.value.gates.find((g) => g.id === "barreau");
    expect(barreau).toBeDefined();
    expect(barreau!.result).toBe("fail");
    expect(barreau!.failingItem).toBe("E-1047");
  });

  it("surfaces INDEX_BUILDING for search when the index is not ready", async () => {
    // Search index readiness is an explicit adapter configuration for this shell.
    const searchAdapter = createAdapter({ backend: null, searchIndexReady: false });
    const result = await searchAdapter.search.query(fixture.case.id, "grievance");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toBe("INDEX_BUILDING");
    expect(result.error).toMatch(/^[A-Z][A-Z0-9_]+$/);
  });

  it("returns the seeded timeline with all four date precisions", async () => {
    const result = await adapter.timeline.list(fixture.case.id);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toHaveLength(4);
    expect(result.value.map((event) => event.precision).sort()).toEqual([
      "approximate",
      "exact",
      "range",
      "unknown",
    ]);
  });

  // ---------------------------------------------------------------------------
  // 3. No component branches on isFixture / isLive
  // ---------------------------------------------------------------------------

  it("exposes the same method signatures in fixture and live mode", () => {
    const live = createAdapter(liveConfig);
    const fixtureAdapter = createAdapter(fixtureConfig);

    // Both modes have identical keys on the adapter surface.
    expect(Object.keys(live).sort()).toEqual(Object.keys(fixtureAdapter).sort());
    for (const group of Object.keys(fixtureAdapter) as Array<keyof typeof fixtureAdapter>) {
      expect(typeof fixtureAdapter[group]).toBe("object");
      expect(Object.keys(fixtureAdapter[group]).sort()).toEqual(
        Object.keys(live[group]).sort(),
      );
    }
  });

  it("does not expose a mode flag to callers", () => {
    // If a caller can ask "am I in fixture mode?", components will branch on it.
    // The adapter must not surface the answer.
    const adapter = createAdapter(fixtureConfig);
    const surface = JSON.stringify(Object.keys(adapter));
    expect(surface).not.toMatch(/isFixture|isLive|mode|fixture|live/i);
  });

  // ---------------------------------------------------------------------------
  // 4. Swap is one file
  // ---------------------------------------------------------------------------

  it("returns ok:false with a named error when the live backend is unreachable", async () => {
    const live = createAdapter(liveConfig);
    const result = await live.cases.get(fixture.case.id);
    // In a unit test environment with no live backend, the live adapter must
    // fail cleanly with a named key, not throw and not silently fall back.
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toBe("BACKEND_UNREACHABLE");
    expect(result.error).toMatch(/^[A-Z][A-Z0-9_]+$/);
  });

  it("never falls back to fixtures when a live backend is configured", async () => {
    const live = createAdapter(liveConfig);
    const result = await live.evidence.get("E-1047");
    // A live adapter that returned the fixture would be the worst kind of silent drift.
    if (result.ok) {
      // If it succeeded, it must have gone through the live path. In this test
      // environment, that path is unreachable, so this branch should not fire.
      throw new Error(
        "live adapter returned data in a test with no backend; it fell back to fixtures",
      );
    }
    expect(result.error).toBe("BACKEND_UNREACHABLE");
  });
});

describe("cases.list / cases.create", () => {
  it("fixture path lists the seed and appends created cases", async () => {
    const a = createAdapter({ backend: null });
    const before = await a.cases.list();
    expect(before.ok && before.value.length).toBe(1);
    const made = await a.cases.create({
      key: "CASE-NEW", title: "N", jurisdiction: "QC", matterType: "labour",
      timezone: "America/Montreal", description: "", memberIds: [],
    });
    expect(made.ok).toBe(true);
    const after = await a.cases.list();
    expect(after.ok && after.value.length).toBe(2);
  });

  it("rejects the seeded key", async () => {
    const a = createAdapter({ backend: null });
    const r = await a.cases.create({
      key: "CASE-2024-018", title: "N", jurisdiction: "QC", matterType: "labour",
      timezone: "America/Montreal", description: "", memberIds: [],
    });
    expect(r).toEqual({ ok: false, error: "CASE_KEY_TAKEN" });
  });

  it("unreachable backend gives BACKEND_UNREACHABLE", async () => {
    const a = createAdapter({ backend: { baseUrl: "http://invalid.invalid" } });
    const r = await a.cases.create({
      key: "K", title: "N", jurisdiction: "QC", matterType: "labour",
      timezone: "America/Montreal", description: "", memberIds: [],
    });
    expect(r).toEqual({ ok: false, error: "BACKEND_UNREACHABLE" });
  });
});

describe("evidence, audit and session cases", () => {
  const bytes = () => new Uint8Array([1, 2, 3]).buffer;

  it("ingest fixture path returns id, hash, duplicate", async () => {
    const a = createAdapter({ backend: null });
    const r = await a.evidence.ingest(fixture.case.id, { name: "n.pdf", bytes: bytes() } as never);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.value.id).toMatch(/^E-/);
      expect(r.value.hash).toMatch(/^[0-9a-f]{64}$/);
      expect(typeof r.value.duplicate).toBe("boolean");
    }
  });

  it("ingest unreachable backend gives BACKEND_UNREACHABLE", async () => {
    const a = createAdapter({ backend: { baseUrl: "http://invalid.invalid" } });
    const r = await a.evidence.ingest(fixture.case.id, { name: "n.pdf", bytes: bytes() } as never);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("BACKEND_UNREACHABLE");
  });

  it("cases.get falls back to a session case", async () => {
    const a = createAdapter({ backend: null });
    const made = await a.cases.create({
      key: "CASE-SESS", title: "S", jurisdiction: "QC", matterType: "labour",
      timezone: "America/Montreal", description: "", memberIds: [],
    });
    expect(made.ok).toBe(true);
    if (made.ok) {
      const got = await a.cases.get(made.value.id);
      expect(got.ok).toBe(true);
    }
  });

  it("audit.list fixture path returns the fixture audit", async () => {
    const a = createAdapter({ backend: null });
    const r = await a.audit.list(fixture.case.id);
    expect(r).toEqual({ ok: true, value: fixture.audit });
  });

  it("session evidence is readable, has empty custody, and is not verifiable", async () => {
    const a = createAdapter({ backend: null });
    const made = await a.evidence.ingest(fixture.case.id, { name: "n.pdf", bytes: new Uint8Array([1, 2, 3]).buffer } as never);
    expect(made.ok).toBe(true);
    if (made.ok) {
      const got = await a.evidence.get(made.value.id);
      expect(got.ok).toBe(true);
      const cu = await a.evidence.custody(made.value.id);
      expect(cu).toEqual({ ok: true, value: [] });
      const v = await a.evidence.verify(made.value.id);
      expect(v.ok).toBe(false);
      if (!v.ok) expect(v.error).toBe("NOT_FOUND");
    }
  });
});

describe("session.get", () => {
  it("returns the seeded fixture session", async () => {
    const a = createAdapter({ backend: null });
    const r = await a.session.get();
    expect(r).toEqual({ ok: true, value: { name: "A. Roy", role: "case_admin" } });
  });
});

describe("members adapter", () => {
  it("lists seeded members and retains invited members with case assignments", async () => {
    const a = createAdapter({ backend: null });
    const before = await a.members.list();
    expect(before.ok).toBe(true);
    if (!before.ok) return;
    expect(before.value[0]).toMatchObject({
      name: "A. Roy",
      email: "a.roy@example.test",
      role: "case_admin",
      caseIds: [fixture.case.id],
    });

    const invited = await a.members.invite({
      email: "new.person@example.test",
      role: "auditor",
      caseIds: [fixture.case.id],
    });
    expect(invited.ok).toBe(true);
    const after = await a.members.list();
    expect(after.ok).toBe(true);
    if (after.ok) {
      expect(after.value.at(-1)).toMatchObject({
        email: "new.person@example.test",
        role: "auditor",
        status: "invited",
        caseIds: [fixture.case.id],
      });
    }
  });

  it("audits role changes with the required reason", async () => {
    const a = createAdapter({ backend: null });
    const changed = await a.members.changeRole("M-2", "auditor", "Temporary audit review");
    expect(changed.ok).toBe(true);
    if (!changed.ok) return;
    expect(changed.value.role).toBe("auditor");
    const audit = await a.audit.list(fixture.case.id);
    expect(audit.ok).toBe(true);
    if (audit.ok) {
      expect(audit.value.at(-1)).toMatchObject({
        event: "member_role_changed",
        memberId: "M-2",
        previousRole: "reviewer",
        role: "auditor",
        reason: "Temporary audit review",
        chain: "linked",
      });
    }
  });
});
