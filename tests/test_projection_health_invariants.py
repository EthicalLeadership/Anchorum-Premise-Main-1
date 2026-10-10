import unittest

from dossier_pipeline.projections_v2 import (ProjectionSnapshot, deep_freeze,
                                              projection_health_report)


def build_snapshot(
    *,
    seen_count: int,
    evidence_packet_count: int,
    custody_event_count: int,
    outbound_send_count: int,
    pending_outbound_count: int,
    processed_record_count: int,
    rejected_record_count: int,
    quarantined_count: int,
    duplicate_record_count: int,
    replay_event_count: int,
    control_tail_hash: str,
) -> ProjectionSnapshot:
    payload = deep_freeze(
        {
            "seen_count": seen_count,
            "evidence_packet_count": evidence_packet_count,
            "custody_event_count": custody_event_count,
            "outbound_send_count": outbound_send_count,
            "pending_outbound_count": pending_outbound_count,
            "processed_record_count": processed_record_count,
            "rejected_record_count": rejected_record_count,
            "quarantined_count": quarantined_count,
            "duplicate_record_count": duplicate_record_count,
            "replay_event_count": replay_event_count,
            "control_tail_hash": control_tail_hash,
        }
    )
    return ProjectionSnapshot(
        seen_count=seen_count,
        evidence_packet_count=evidence_packet_count,
        custody_event_count=custody_event_count,
        outbound_send_count=outbound_send_count,
        pending_outbound_count=pending_outbound_count,
        processed_record_count=processed_record_count,
        rejected_record_count=rejected_record_count,
        quarantined_count=quarantined_count,
        duplicate_record_count=duplicate_record_count,
        replay_event_count=replay_event_count,
        control_tail_hash=control_tail_hash,
        payload=payload,
    )


class ProjectionHealthInvariantTests(unittest.TestCase):
    def test_empty_processed_snapshot_is_warning(self):
        snapshot = build_snapshot(
            seen_count=0,
            evidence_packet_count=0,
            custody_event_count=0,
            outbound_send_count=0,
            pending_outbound_count=0,
            processed_record_count=0,
            rejected_record_count=0,
            quarantined_count=0,
            duplicate_record_count=0,
            replay_event_count=0,
            control_tail_hash="tail",
        )

        report = projection_health_report(snapshot)

        self.assertEqual(report["severity"], "WARNING")
        self.assertTrue(report["ok"])

    def test_quarantine_or_rejection_forces_critical(self):
        quarantined = build_snapshot(
            seen_count=1,
            evidence_packet_count=2,
            custody_event_count=2,
            outbound_send_count=0,
            pending_outbound_count=0,
            processed_record_count=1,
            rejected_record_count=0,
            quarantined_count=1,
            duplicate_record_count=0,
            replay_event_count=3,
            control_tail_hash="tail",
        )
        rejected = build_snapshot(
            seen_count=2,
            evidence_packet_count=3,
            custody_event_count=3,
            outbound_send_count=0,
            pending_outbound_count=0,
            processed_record_count=2,
            rejected_record_count=1,
            quarantined_count=0,
            duplicate_record_count=0,
            replay_event_count=4,
            control_tail_hash="tail",
        )

        quarantined_report = projection_health_report(quarantined)
        rejected_report = projection_health_report(rejected)

        self.assertEqual(quarantined_report["severity"], "CRITICAL")
        self.assertEqual(rejected_report["severity"], "CRITICAL")

    def test_consistency_flags_track_count_invariants(self):
        consistent = build_snapshot(
            seen_count=3,
            evidence_packet_count=4,
            custody_event_count=4,
            outbound_send_count=0,
            pending_outbound_count=0,
            processed_record_count=3,
            rejected_record_count=0,
            quarantined_count=0,
            duplicate_record_count=0,
            replay_event_count=6,
            control_tail_hash="tail",
        )
        inconsistent = build_snapshot(
            seen_count=1,
            evidence_packet_count=1,
            custody_event_count=1,
            outbound_send_count=0,
            pending_outbound_count=0,
            processed_record_count=3,
            rejected_record_count=0,
            quarantined_count=0,
            duplicate_record_count=0,
            replay_event_count=2,
            control_tail_hash="tail",
        )

        consistent_report = projection_health_report(consistent)
        inconsistent_report = projection_health_report(inconsistent)

        self.assertTrue(consistent_report["consistency"]["evidence_vs_control"])
        self.assertTrue(consistent_report["consistency"]["seen_vs_control"])
        self.assertTrue(consistent_report["consistency"]["replay_monotonic"])

        self.assertFalse(inconsistent_report["consistency"]["evidence_vs_control"])
        self.assertFalse(inconsistent_report["consistency"]["seen_vs_control"])
        self.assertFalse(inconsistent_report["consistency"]["replay_monotonic"])


if __name__ == "__main__":
    unittest.main()
