# Audit report - Anchorum

- generated: 2026-10-25 19:09 UTC
- root: `/home/kark/anchorum-prem-main(1)/anchorum-prem-main`
- tests: run
- method: static scan + live pytest; every finding cites file:line

## Summary

| id | check | status |
|----|-------|--------|
| C1 | Test suite | **PASS** |
| C10 | 'Guarantee' language | **PASS** |
| C2 | Gate module | **PASS** |
| C8 | Append-only log | **REVIEW** |
| C11 | Export path | **PASS** |
| C12 | Fingerprint source | **PASS** |
| C3 | Gate wiring | **PASS** |
| C4 | Role branch | **PASS** |
| C5 | Registry | **PASS** |
| C6 | Content hashing | **PASS** |
| C7 | Audit sink | **PASS** |
| C9 | Privacy / compliance doc | **PASS** |

Counts: FAIL=0, PASS=10, REVIEW=1


## Details

### C1 - Test suite - **PASS**

*Does the full suite pass, right now?*

Evidence:

```
686 passed, 2 warnings in 19.20s
```

### C10 - 'Guarantee' language - **PASS**

*Does marketing copy promise a guarantee?*

Note: claim language replaced with 'auditable'

Evidence:

```
grep -ri "guarantee" --include="*.md" . | grep -v ".venv" | grep -v "node_modules" | grep -v "audit_report.md"
(no matches)
```

### C2 - Gate module - **PASS**

*Does barreau_gate.py exist, and what is the ID regex?*

Note: regex is now 7-digit; jurisdiction confirmed

Evidence:

```
barreau_gate.py:14: BAR_ID_RE = re.compile(r"^[0-9]{7}$")
tests/test_barreau_gate.py:GOOD_ID = "1234567"
```

### C8 - Append-only log - **REVIEW**

*Are audit/log records protected from update/delete?*

Note: mutation calls found in test files; confirm append-only for production

Evidence:

```
tests/test_audit_hmac.py:68: conn.execute(f"UPDATE audit_logs SET {column} = ? WHERE id = ?",
tests/test_audit_badge_honesty.py:68: conn.execute("UPDATE audit_logs SET record_hash = '' WHERE id = ?", (row_id,))
```

### C11 - Export path - **PASS**


### C12 - Fingerprint source - **PASS**


### C3 - Gate wiring - **PASS**


### C4 - Role branch - **PASS**


### C5 - Registry - **PASS**


### C6 - Content hashing - **PASS**


### C7 - Audit sink - **PASS**


### C9 - Privacy / compliance doc - **PASS**

