"""Pins for the engine binding §7.2 requires of the analysis layer.

Three properties, each stated by the plan as a requirement rather than an
implementation detail:

* the lexicon is read **once** and every scope is projected through that one
  engine, not re-loaded per scope;
* a projection reports its own hashes as ``rules_hash`` / ``config_hash`` - the
  names ``ProjectionResponse`` already uses, which the plan says must not be
  renamed to match the product;
* the analysis record surfaces ``rules_hash`` under the product-facing key
  ``lexiconHash``, and ``engine.fingerprint()`` re-derives that same pair, so a
  stored analysis can be tied to the lexicon that produced it.

The third is the mapping the plan says "must be written down rather than
assumed". This module writes it down executably: the API key and the model
attribute are asserted to carry the same value, so renaming either side fails
here rather than only in production.
"""

from interface import analysis, engine

TEXT = "A block of contract text about a modification and its consideration."
BYTES = TEXT.encode("utf-8")


class TestLexiconIsLoadedOnce:
    def test_the_engine_object_is_shared_across_calls(self):
        # `@lru_cache(maxsize=1)` on both factory functions. Dropping the
        # decorator fails this, and the lexicon is then parsed again for every
        # scope a document is cut into.
        assert engine.engine() is engine.engine()
        assert engine.engine_doctrine() is engine.engine_doctrine()

    def test_projecting_many_scopes_reads_the_lexicon_once(self, monkeypatch):
        loads: list[str] = []
        real_load = engine.load_lexicon

        def counting_load(path):
            loads.append(path)
            return real_load(path)

        engine.engine.cache_clear()
        monkeypatch.setattr(engine, "load_lexicon", counting_load)
        try:
            for _ in range(5):
                engine.project_text(TEXT)
            assert len(loads) == 1, f"lexicon read {len(loads)} times, expected 1"
        finally:
            monkeypatch.undo()
            engine.engine.cache_clear()


class TestProjectionNamesItsOwnHashes:
    def test_a_projection_reports_rules_hash_and_config_hash(self):
        projection = engine.project_text(TEXT)
        assert projection.rules_hash
        assert projection.config_hash

    def test_fingerprint_agrees_with_a_live_projection(self):
        projection = engine.project_text(TEXT)
        assert engine.fingerprint() == (projection.rules_hash, projection.config_hash)


class TestRecordSurfacesRulesHashAsLexiconHash:
    def test_the_record_carries_the_live_projection_hash_under_the_product_key(self):
        projection = engine.project_text(TEXT)
        record = analysis.analyse(BYTES, "note.txt", "text/plain")

        assert record["status"] == analysis.STATUS_PROCESSED
        assert record["projection"]["lexiconHash"] == projection.rules_hash
        assert record["projection"]["configHash"] == projection.config_hash

    def test_the_model_attribute_name_is_not_the_key_the_product_reads(self):
        # One-directional on purpose: the key is `lexiconHash` because that is
        # what it identifies to the product, while the field on the model is
        # `rules_hash` because that is what it is. Publishing the model's own
        # name would leak the implementation into the record.
        record = analysis.analyse(BYTES, "note.txt", "text/plain")
        assert "lexiconHash" in record["projection"]
        assert "rules_hash" not in record["projection"]

    def test_the_doctrine_block_carries_the_doctrine_lexicon_hash(self):
        doctrine = engine.project_doctrine(TEXT)
        record = analysis.analyse(BYTES, "note.txt", "text/plain")

        assert record["doctrine"]["lexiconHash"] == doctrine.rules_hash
        assert record["doctrine"]["configHash"] == doctrine.config_hash

    def test_the_two_lexicons_are_distinguishable_by_hash(self):
        # If the doctrine lexicon were ever bound to the risk register's hash,
        # every re-analysis check would compare a document to itself.
        record = analysis.analyse(BYTES, "note.txt", "text/plain")
        assert record["projection"]["lexiconHash"] != record["doctrine"]["lexiconHash"]
