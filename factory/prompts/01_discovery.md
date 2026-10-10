# Discovery prompt — v0.1.0

Produce a single JSON document describing a gateway for the ANCHORUM
platform. Return JSON only. No prose, no markdown fences.

## Inputs

- vertical: {{vertical}}
- jurisdiction: {{jurisdiction}}

## Output schema

```json
{
  "documents": [
    {
      "id": "snake_case_id",
      "label": "Human Label",
      "filename_glob": "*substring*",
      "mime_types": ["application/pdf"],
      "required_fields": ["field_one", "field_two"],
      "extractor": "pdf_text",
      "retention_days": 2555,
      "gaps": ["what a domain expert must verify"]
    }
  ],
  "actors": [
    {"id": "snake_case_role", "display": "Human Role",
     "patterns": ["keyword", "name@domain.example"], "gaps": []}
  ],
  "regulations": [
    {"id": "CITATION-ID", "title": "Full title", "status": "verified",
     "url": "https://... or null", "gaps": []}
  ],
  "risk_patterns": [
    {"id": "snake_case_id", "description": "What this detects",
     "severity": "high", "gaps": []}
  ],
  "routes": ["QUARANTINE_REVIEW", "HOLD_FOR_REVIEW"]
}

