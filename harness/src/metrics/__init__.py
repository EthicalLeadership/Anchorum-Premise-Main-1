"""Metrics collectors. All collectors are stdlib-only and degrade
gracefully: a collector that cannot read its source returns a partially
filled record with a `*_present` false flag rather than raising."""
