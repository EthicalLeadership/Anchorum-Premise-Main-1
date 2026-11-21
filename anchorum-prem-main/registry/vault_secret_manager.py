List[KeyVersion]:
        """Retrieve the complete history of key versions."""
        return self._key_history.copy()
    
    def _compute_chain_hash(self, predecessor_key_id: Optional[str], 
                            public_key: bytes) -> str:
        """Compute hash for signature chain integrity."""
        if predecessor_key_id is None:
            return hashlib.sha256(public_key).hexdigest()
        
        combined = f"{predecessor_key_id}:{public_key.hex()}"
        return hashlib.sha256(combined.encode()).hexdigest()


# ... existing code ...
