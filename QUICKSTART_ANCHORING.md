# Quickstart — Anchoring DOSSIER-PIPELINE

## What this adds
- A local anchor file derived from the control-chain tail hash
- Optional OpenTimestamps stamping
- Optional Cloudflare DNS TXT publication for public verification

## Files added
- `dossier_pipeline/anchor_core.py`
- `dossier_pipeline/anchor_opentimestamps.py`
- `dossier_pipeline/anchor_dnssec.py`
- `dossier_pipeline/anchor.py`
- `dossier_pipeline/anchor_cli.py`
- `setup_anchoring.sh`

## One-time setup
```bash
export CF_ZONE_ID="paste-your-zone-id-here"
export CF_API_TOKEN="paste-your-token-here"
export DOSSIER_ID="DOSSIER-PIPELINE"
bash setup_anchoring.sh
```

## Create an anchor
```bash
python3 -m dossier_pipeline.anchor_cli anchor-now
```

Expected output:
```text
Anchor result: SUCCESS
  Merkle root: ...
  Tail hash: ...
  OpenTimestamps: ...
  DNSSEC: ...
  Anchor file: ...
```

## Verify local anchor artifacts
```bash
python3 -m dossier_pipeline.anchor_cli verify-anchors
```

## Check DNS credentials and target name
```bash
python3 -m dossier_pipeline.anchor_cli dns-check
```

## Public verification
If DNS publishing is enabled, the TXT record is published at:

```text
dossier-02.chain.creovate.digital
```

Example query:
```bash
dig TXT dossier-02.chain.creovate.digital
```

## Notes
- DNS publishing is best-effort and will fail cleanly if credentials are missing.
- OpenTimestamps support is also best-effort; if the `ots` command is unavailable, a local placeholder proof is created.
- The anchor file is written into the output directory and is derived from the current control-chain tail hash.
