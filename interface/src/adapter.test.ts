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
    expect(result.value.title).toBe("Dupont v. Acme");
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
