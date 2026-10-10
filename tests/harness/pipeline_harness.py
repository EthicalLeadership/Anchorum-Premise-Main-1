import tempfile
from pathlib import Path

from dossier_pipeline.pipeline import DossierPipeline


class PipelineTestHarness:
    """
    Lightweight observable wrapper around DossierPipeline for invariant tests.

    The harness exposes a single truth surface for the major persisted stores:
    - seen registry
    - control-chain records
    - outbound registry
    - evidence store snapshot
    """

    def __init__(self, output_dir: str | None = None, dossier_id: str = "TEST-DOSSIER-PIPELINE"):
        self._tempdir = tempfile.TemporaryDirectory() if output_dir is None else None
        self.output_dir = output_dir or self._tempdir.name
        self.pipeline = DossierPipeline(dossier_id=dossier_id, output_dir=self.output_dir)

    def ingest(self, raw_email_bytes: bytes):
        return self.pipeline.process_email(raw_email_bytes)

    def state(self):
        evidence_report = self.pipeline.evidence.verify()
        return {
            "seen": self.pipeline.seen.count(),
            "chain": self.pipeline.control.get_all_records(),
            "outbound": {
                "registry": self.pipeline.outbound.get_all(),
                "pending": self.pipeline.outbound.get_pending(),
                "outbox": self.pipeline.outbound.get_outbox(),
            },
            "evidence": {
                "system_state": evidence_report.system_state.value,
                "integrity_pass": evidence_report.integrity_pass,
                "packet_count": evidence_report.total_packets,
                "custody_count": evidence_report.total_custody_events,
                "tail_hash": evidence_report.tail_hash,
                "anchor_hash": evidence_report.anchor_hash,
            },
            "pipeline_state": self.pipeline.current_state,
            "state_history": list(self.pipeline.state_history),
        }

    def close(self):
        self.pipeline.close()
        if self._tempdir is not None:
            self._tempdir.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
