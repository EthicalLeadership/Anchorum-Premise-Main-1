# Egress inventory

**Scope:** every place in this repository that can open a network connection to
a destination outside the host, with the default when no environment variable
is set.

**Why this exists.** The architecture specification requires an egress
inventory as a precondition for any restricted, private-AI or air-gapped
deployment claim (`SYSTEM_ARCHITECTURE.md` §3 deployment profiles, `HARD-11`,
`HARD-12`), and the independent build audit recorded its absence as audit
finding F-06. A deployment cannot constrain what it has not enumerated.

**Method (so this list can be re-derived rather than trusted).**

```bash
grep -rn "https\?://" --include=*.py . | grep -v __pycache__ | grep -v "\.venv"
grep -rln "import requests\|import httpx\|urllib.request\|import imaplib\|import smtplib\|import socket\|urlopen" --include=*.py . \
  | grep -v __pycache__ | grep -v "\.venv"
```

**Limits of that method.** It finds literal URLs and direct use of HTTP/IMAP
libraries in first-party code. It would _not_ find a destination assembled at
runtime from configuration, nor egress performed by a third-party library that
this code merely calls. Both are called out below where they apply.

## Call sites

| #   | Module                                 | Destination                                                                                        | Default                                                    | Configurable by                                                    | Direction                             | Payload                                                  |
| --- | -------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------- | -------------------------------------------------------- |
| 1   | `classifier.py` (`_anthropic`)         | api.anthropic.com (SDK)                                                                            | active only if the anthropic backend is selected           | backend selection; `CLF_MODEL` (default `claude-3-5-haiku-latest`) | outbound request / inbound completion | the classified sentence and `classifier_prompt.txt`      |
| 2   | `classifier.py` (`_openai`)            | api.openai.com (SDK)                                                                               | active only if the openai backend is selected              | backend selection; `CLF_MODEL` (default `gpt-4o-mini`)             | outbound / inbound                    | as above                                                 |
| 3   | `classifier.py` (`_ollama`)            | `http://localhost:11434/api/generate`                                                              | **local**                                                  | `OLLAMA_URL`                                                       | outbound / inbound                    | as above; stays on-host unless `OLLAMA_URL` is repointed |
| 4   | `classifier.py` (`_command`)           | _arbitrary_ whatever the configured command contacts                                             | active only if the command backend is selected             | `_command(cmd)` executes a subprocess                              | **unbounded**                         | **unbounded**                                            |
| 5   | `classify.py`                          | `http://127.0.0.1:8002/v1/chat/completions`                                                        | **local** (OpenAI-compatible local endpoint)               | `CLASSIFIER_URL` (also `CLASSIFIER_MODEL`, `CLASSIFIER_KEY`)       | outbound / inbound                    | one sentence                                             |
| 6   | `dossier_pipeline/anchor_dnssec.py:41` | `https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records`                                 | **external, when invoked**                                 | Cloudflare credentials from the environment                        | outbound request / API response       | the anchor TXT record (a hash), zone id, API token       |
| 7   | `dossier_pipeline/anchor_dnssec.py:77` | publishes a name under `anchorumzero-trust.com`                                                    | fixed default domain, overridable by the `domain` argument | caller argument                                                    | n/a (names the published record)      | the anchor record name                                   |
| 8   | `dossier_pipeline/proton_connector.py` | `127.0.0.1:1143` (ProtonMail Bridge) by default; `imap.protonmail.ch:993` as a documented fallback | **local bridge**                                           | `host` / `port` constructor arguments                              | inbound fetch (and append)            | mailbox contents; implicit TLS on the fallback           |

## Assessment

**Default posture is local.** Five of the eight rows are loopback by default
(`OLLAMA_URL`, `CLASSIFIER_URL`, the Proton Bridge, and the Cloudflare/domain
rows are only reached by explicit anchor operations). A stock install does not
contact a remote LLM provider.

**Two rows carry real risk.**

- **Row 4 (`_command`)** is the significant one. It executes an arbitrary
  subprocess to obtain a classification, so its egress and its privilege are
  bounded only by the command that is configured. In a restricted deployment
  this backend must be disabled outright, not merely left unconfigured.
- **Rows 1–2 (`_anthropic`, `_openai`)** transmit evidence-derived text to a
  third-party provider. That is a data-residency and retention decision, not a
  code defect, but it must be an explicit, reviewed choice per deployment
  (`SYSTEM_ARCHITECTURE.md` §10, "AI" gate).

**Transitive dependency note.** `opentelemetry-api` is present in
`requirements.lock`. Only the API package is present there is no
`opentelemetry-sdk` and no exporter in the closure so it cannot transmit
anything on its own. Adding an SDK or an exporter would introduce egress that
this inventory does not cover, and that addition must be treated as a change to
the egress surface.

**No SMTP, no generic socket use, and no third-party egress helper** was found
in first-party code by the method above.

## Deployment requirement

For any restricted or air-gapped profile, all of the following must hold and be
tested end-to-end before the claim is made:

1. Rows 1, 2 and 4 are unreachable by configuration (ideally absent from the
   build), not merely unset.
2. Rows 3 and 5 point at an on-host model endpoint.
3. Row 6 is either disabled or reached through a controlled proxy, and the
   anchor publication path has a documented offline equivalent.
4. Row 8 uses a local bridge only; the `imap.protonmail.ch` fallback is
   disabled.
5. Egress is denied by default at the network layer, so that a future
   reintroduction of any row fails closed rather than silently connecting.
