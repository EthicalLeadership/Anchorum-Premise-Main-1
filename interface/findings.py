import re
from datetime import datetime, timezone


# Pattern to detect promises of follow-up (e.g., "I'll email", "will follow")
PROMISE_REGEX = re.compile(r"\b(I'll|I will|we will)\s+(email|send|follow|confirm)|\bwill follow\b", re.IGNORECASE)


def _parse_time(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def evaluate_findings(
    messages: list[dict],
    reply_deadline_days: int = 5,
    followup_deadline_days: int = 3,
    as_of: str | None = None,
) -> list[dict]:
    if not messages:
        return []

    if as_of is None:
        as_of = datetime.now(timezone.utc).isoformat()
    as_of_dt = _parse_time(as_of)

    # Sort messages by time
    msgs = sorted(messages, key=lambda m: _parse_time(m["timestamp"]))
    findings = []

    for m in msgs:
        if not m.get("needs_reply"):
            continue

        m_time = _parse_time(m["timestamp"])

        # Find the first reply from the to_actor back to the from_actor
        reply = next(
            (r for r in msgs
             if _parse_time(r["timestamp"]) > m_time
             and r["from_actor"] == m["to_actor"]
             and r["to_actor"] == m["from_actor"]),
            None
        )

        if reply:
            reply_time = _parse_time(reply["timestamp"])
            delta_days = (reply_time - m_time).days
            if delta_days > reply_deadline_days:
                findings.append({
                    "id": f"R1-{m['id']}",
                    "rule": "Rule 1 (reply time)",
                    "title": "Late reply",
                    "triggering_message_id": m["id"],
                    "evidence_message_ids": [m["id"], reply["id"]],
                    "rationale": f"The reply came after {delta_days} days (limit {reply_deadline_days} days).",
                    "status": "candidate"
                })
        else:
            delta_days = (as_of_dt - m_time).days
            if delta_days > reply_deadline_days:
                findings.append({
                    "id": f"R1-{m['id']}",
                    "rule": "Rule 1 (reply time)",
                    "title": "Still unanswered",
                    "triggering_message_id": m["id"],
                    "evidence_message_ids": [m["id"]],
                    "rationale": f"No reply for {delta_days} days (limit {reply_deadline_days} days).",
                    "status": "candidate"
                })

    # Rule 2: Promised follow-up
    for m in msgs:
        body = m.get("body", "") or ""
        if not PROMISE_REGEX.search(body):
            continue
        
        m_time = _parse_time(m["timestamp"])
        
        # Look for the promised follow-up message
        follow_up = None
        for candidate in msgs:
            c_time = _parse_time(candidate["timestamp"])
            if c_time > m_time and \
               candidate["from_actor"] == m["from_actor"] and \
               candidate["to_actor"] == m["to_actor"]:
                follow_up = candidate
        
        # If no follow-up exists at all, check as_of deadline
        if follow_up is None:
            delta_days = (as_of_dt - m_time).days
            if delta_days > followup_deadline_days:
                findings.append({
                    "id": f"R2-{m['id']}",
                    "rule": "Rule 2 (promised follow-up)",
                    "title": "Promised follow-up not found",
                    "triggering_message_id": m["id"],
                    "evidence_message_ids": [m["id"]],
                    "rationale": f"No later email from {m['from_actor']} to {m['to_actor']} within {followup_deadline_days} days.",
                    "status": "candidate"
                })
            continue  # No follow-up found; already handled above
        
        # Check if we have a valid email-based follow-up within deadline
        follow_up_time = _parse_time(follow_up["timestamp"])
        delta_days = (follow_up_time - m_time).days
        channel = getattr(follow_up, "channel", "") or follow_up.get("channel", "")
        
        # Need channel == "email" and within deadline
        if channel != "email":
            # Not an email-based follow-up, check as_of deadline
            delta_days_asof = (as_of_dt - m_time).days
            if delta_days_asof > followup_deadline_days:
                findings.append({
                    "id": f"R2-{m['id']}",
                    "rule": "Rule 2 (promised follow-up)",
                    "title": "Promised follow-up not found",
                    "triggering_message_id": m["id"],
                    "evidence_message_ids": [m["id"]],
                    "rationale": f"No later email from {m['from_actor']} to {m['to_actor']} within {followup_deadline_days} days.",
                    "status": "candidate"
                })
            continue
        
        if delta_days <= followup_deadline_days:
            continue  # Found valid follow-up; no finding needed
        
        # Promised but not followed up in time
        findings.append({
            "id": f"R2-{m['id']}",
            "rule": "Rule 2 (promised follow-up)",
            "title": "Promised follow-up not found",
            "triggering_message_id": m["id"],
            "evidence_message_ids": [m["id"]],
            "rationale": f"No later email from {m['from_actor']} to {m['to_actor']} within {followup_deadline_days} days.",
            "status": "candidate"
        })

    return sorted(findings, key=lambda f: f["triggering_message_id"])
