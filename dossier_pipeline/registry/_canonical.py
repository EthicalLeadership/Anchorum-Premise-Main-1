try:
    from blackstar.shared.canonical import canonical_json, sha256_hex
except ImportError:
    import hashlib, json
    def canonical_json(obj):
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    def sha256_hex(b):
        return hashlib.sha256(b).hexdigest()
