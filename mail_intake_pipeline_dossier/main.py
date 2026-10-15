"""
Dossier DOSSIER-PIPELINE Integrated CLI Entry Point

Usage:
    python -m dossier_pipeline.main ingest-proton --limit 100
    python -m dossier_pipeline.main ingest-dir ./emails
    python -m dossier_pipeline.main export-json
    python -m dossier_pipeline.main export-md
    python -m dossier_pipeline.main verify-chain
    python -m dossier_pipeline.main demo
    python -m dossier_pipeline.main enforce
    python -m dossier_pipeline.main verify
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import getaddresses
from glob import glob
from pathlib import Path

from .contracts import ResultStatus
from .evidence import EvidenceSignerUnbound
from .pipeline import DossierPipeline
from .proton_connector import ProtonMailConnector

def load_actor_rules(config_path: str | None = None) -> dict:
    """Load actor classification rules from a JSON config file.

    The default path is <repo>/config/actors.example.json. A real
    deployment supplies its own file via --actor-config or the
    ACTORS_CONFIG env var. The example ships with neutral placeholders,
    never client data.
    """
    import json as _json
    import os as _os
    from pathlib import Path as _Path

    default = _Path(__file__).resolve().parent.parent / "config" / "actors.example.json"
    chosen = config_path or _os.environ.get("ACTORS_CONFIG")
    path = _Path(chosen).expanduser() if chosen else default
    if not path.is_file():
        path = default
    with path.open("r", encoding="utf-8") as fh:
        return _json.load(fh)


DEFAULT_ACTOR_RULES = load_actor_rules()

# Where custody data goes when nothing configures it. Relative, but resolved to
# an absolute path before use so the destination is never implied (F-11).
DEFAULT_OUTPUT_DIR = "./output"

def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_addresses(value: str):
    decoded = _decode_header_value(value)
    return [addr.lower() for _, addr in getaddresses([decoded]) if addr]


def _message_subject(msg) -> str:
    return _decode_header_value(msg.get("Subject", ""))


def _message_date(msg) -> str:
    return _decode_header_value(msg.get("Date", ""))


def _build_actor_audit_summary(messages_by_box, owner_email: str):
    owner = (owner_email or "").strip().lower()
    summary = {}
    for actor_id, rule in DEFAULT_ACTOR_RULES.items():
        summary[actor_id] = {
            "actor_id": actor_id,
            "display": rule["display"],
            "patterns": list(rule["patterns"]),
            "sent_count": 0,
            "inbox_count": 0,
            "responded": False,
            "recent_sent": [],
            "recent_inbox": [],
        }

    for box_name, raw_messages in messages_by_box.items():
        for raw in raw_messages:
            msg = message_from_bytes(raw)
            from_addrs = _extract_addresses(msg.get("From", ""))
            to_addrs = _extract_addresses(msg.get("To", ""))
            cc_addrs = _extract_addresses(msg.get("Cc", ""))
            all_addrs = list({*(from_addrs or []), *(to_addrs or []), *(cc_addrs or [])})

            subject = _message_subject(msg)
            date_value = _message_date(msg)
            sample = {
                "date": date_value,
                "subject": subject,
                "from": _decode_header_value(msg.get("From", "")),
                "to": _decode_header_value(msg.get("To", "")),
                "mailbox": box_name,
            }

            combined = " ".join(all_addrs).lower()
            for actor_id, rule in DEFAULT_ACTOR_RULES.items():
                matched = any(p.lower() in combined for p in rule["patterns"])
                if not matched:
                    continue

                is_outbound = owner and owner in from_addrs
                is_inbound = owner and (owner in to_addrs or owner in cc_addrs)

                if box_name.upper() == "SENT" or is_outbound:
                    summary[actor_id]["sent_count"] += 1
                    summary[actor_id]["recent_sent"].append(sample)
                if box_name.upper() == "INBOX" or is_inbound:
                    summary[actor_id]["inbox_count"] += 1
                    summary[actor_id]["recent_inbox"].append(sample)
                break

    for data in summary.values():
        data["responded"] = data["inbox_count"] > 0
        data["recent_sent"] = data["recent_sent"][-3:]
        data["recent_inbox"] = data["recent_inbox"][-3:]

    return summary


def cmd_audit_actors(args, config):
    if not config["password"]:
        print("ERROR: Proton IMAP password not set in env, .env, or --config file.", file=sys.stderr)
        sys.exit(1)

    use_ssl = config["use_ssl"] if config.get("use_ssl") else (config["port"] == 993)
    connector = ProtonMailConnector(
        email=config["email"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
        use_ssl=use_ssl,
    )

    requested_mailboxes = [m.strip() for m in args.mailboxes.split(",") if m.strip()]
    if not requested_mailboxes:
        requested_mailboxes = ["INBOX", "Sent"]

    print(
        f"Connecting to ProtonMail IMAP ({config['host']}:{config['port']}) "
        f"for actor audit, mailboxes={requested_mailboxes}, limit={args.limit}..."
    )
    try:
        connector.connect()
        messages_by_box = {}
        for box in requested_mailboxes:
            messages_by_box[box] = connector.fetch_all(limit=args.limit, mailbox=box)
    except ConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        connector.disconnect()

    summary = _build_actor_audit_summary(messages_by_box, config["email"])
    ordered = sorted(summary.values(), key=lambda x: x["display"].lower())

    print("\n" + "=" * 78)
    print(f"ACTOR RESPONSE AUDIT {config['dossier_id']}")
    print("=" * 78)
    for item in ordered:
        status = "RESPONDED" if item["responded"] else "NO RESPONSE"
        print(f"\n- {item['display']}: {status}")
        print(f"  sent={item['sent_count']} | inbox={item['inbox_count']}")
        if item["recent_inbox"]:
            for sample in item["recent_inbox"]:
                print(f"  IN  | {sample['date']} | {sample['subject'][:70]}")
        if item["recent_sent"]:
            for sample in item["recent_sent"]:
                print(f"  OUT | {sample['date']} | {sample['subject'][:70]}")

    no_response = [item["display"] for item in ordered if item["sent_count"] > 0 and item["inbox_count"] == 0]
    print("\n" + "-" * 78)
    print("NO-RESPONSE ACTORS (sent > 0, inbox = 0):")
    if no_response:
        for name in no_response:
            print(f"  - {name}")
    else:
        print("  - none")

    if args.write_json:
        out_dir = Path(config["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{config['dossier_id']}_actor_audit_{stamp}.json"
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "dossier_id": config["dossier_id"],
            "mailboxes": requested_mailboxes,
            "limit": args.limit,
            "email_owner": config["email"],
            "actors": ordered,
            "no_response": no_response,
        }
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved JSON report: {out_path}")


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _load_json_config(config_path: str):
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a top-level JSON object.")
    return data


def _load_dotenv(path: str = ".env"):
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_config(config_path: str = None):
    dotenv = _load_dotenv()

    def env(name, default):
        return os.getenv(name, dotenv.get(name, default))

    config = {
        "email": env("PROTON_EMAIL", "user@protonmail.com"),
        "password": env("PROTON_IMAP_PASSWORD", ""),
        "host": env("PROTON_IMAP_HOST", "127.0.0.1"),
        "port": int(env("PROTON_IMAP_PORT", "1143")),
        "use_ssl": _parse_bool(env("PROTON_IMAP_USE_SSL", "false")),
        "mailbox": env("PROTON_IMAP_MAILBOX", "INBOX"),
        "dossier_id": env("DOSSIER_ID", "DOSSIER-PIPELINE"),
        "output_dir": env("OUTPUT_DIR", "./output"),
        "batch_size": int(env("PIPELINE_BATCH_SIZE", "50")),
    }

    if not config_path:
        return config

    raw_config = _load_json_config(config_path)
    proton = raw_config.get("proton", {})
    pipeline = raw_config.get("pipeline", {})

    if not isinstance(proton, dict):
        raise ValueError("'proton' config section must be a JSON object.")
    if not isinstance(pipeline, dict):
        raise ValueError("'pipeline' config section must be a JSON object.")

    config["dossier_id"] = raw_config.get("dossier", raw_config.get("dossier_id", config["dossier_id"]))
    config["output_dir"] = raw_config.get("output_dir", config["output_dir"])
    config["email"] = proton.get("username", proton.get("email", config["email"]))
    config["password"] = proton.get("password", config["password"])
    config["host"] = proton.get("host", config["host"])
    config["port"] = int(proton.get("port", config["port"]))
    config["use_ssl"] = _parse_bool(proton.get("use_ssl", config["use_ssl"]))
    config["mailbox"] = proton.get("mailbox", config["mailbox"])
    config["batch_size"] = int(pipeline.get("batch_size", config["batch_size"]))

    return config


def _resolve_output_dir(config: dict) -> Path:
    """Resolve the data directory to an absolute path and record the decision.

    The default was the string ``"./output"`` relative to whatever directory
    the process happened to start in. Two invocations of the same command from
    two different directories therefore wrote custody data to two different
    places, and nothing in the output said which. Resolving here does not move
    any files: it resolves the same destination to an explicit absolute path so
    the location is visible and reviewable (audit finding F-11).

    The library layer keeps taking whatever directory it is handed; deciding
    where that is belongs to the entry point.
    """
    configured = config.get("output_dir") or DEFAULT_OUTPUT_DIR
    return Path(configured).expanduser().resolve()


def _build_pipeline(config):
    return DossierPipeline(dossier_id=config["dossier_id"], output_dir=config["output_dir"])


def cmd_enforce(args, config):
    pipeline = _build_pipeline(config)
    report = pipeline.projection_health_report()
    print("ENFORCEMENT REPORT")
    print(f"Severity: {report['severity']}")
    print(f"OK:       {report['ok']}")
    print(f"Tail:     {report['snapshot']['control_tail_hash']}")
    print(f"Seen:     {report['snapshot']['seen_count']}")
    print(f"Records:  {report['snapshot']['processed_record_count']}")


def cmd_verify(args, config):
    pipeline = _build_pipeline(config)
    replay_report = pipeline.replay.verify()
    chain_report = pipeline.control.verify_chain()
    projection_report = pipeline.projection_health_report()
    # Evidence signatures can only be checked with the key that made them, and
    # opening the store deliberately no longer does that for you. This call is
    # what makes the command's claim mean something: it fails closed without
    # GDC_EVIDENCE_SECRET rather than reporting a pass it cannot support. An
    # operator who asked for verification and cannot have it deserves a sentence
    # saying so, not a traceback.
    try:
        evidence_report = pipeline.evidence.verify()
    except EvidenceSignerUnbound as exc:
        print("VERIFICATION REPORT", file=sys.stderr)
        print("Evidence integrity: NOT VERIFIED", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        sys.exit(2)
    print("VERIFICATION REPORT")
    print(f"Chain integrity:    {'PASS' if chain_report['integrity_pass'] else 'FAIL'}")
    print(f"Replay integrity:   {'PASS' if replay_report.integrity_pass else 'FAIL'}")
    print(
        f"Evidence integrity: {'PASS' if evidence_report.integrity_pass else 'FAIL'}"
        f" ({evidence_report.total_packets} packets,"
        f" {evidence_report.total_custody_events} custody events)"
    )
    print(f"Projection OK:      {projection_report['ok']}")
    print(f"Projection sev:     {projection_report['severity']}")

    if (
        (not chain_report["integrity_pass"])
        or (not replay_report.integrity_pass)
        or (not evidence_report.integrity_pass)
        or (not projection_report["ok"])
    ):
        sys.exit(2)


def cmd_ingest_proton(args, config):
    if not config["password"]:
        print("ERROR: Proton IMAP password not set in env, .env, or --config file.", file=sys.stderr)
        sys.exit(1)

    use_ssl = config["use_ssl"] if config.get("use_ssl") else (config["port"] == 993)
    pipeline = _build_pipeline(config)

    connector = ProtonMailConnector(
        email=config["email"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
        use_ssl=use_ssl,
    )

    limit = args.limit if args.limit is not None else config["batch_size"]

    print(
        f"Connecting to ProtonMail IMAP "
        f"({config['host']}:{config['port']}, mailbox={config['mailbox']})..."
    )
    try:
        connector.connect()
    except ConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching up to {limit} unread messages...")
    raw_messages = connector.fetch_unread(limit=limit, mailbox=config["mailbox"])
    connector.disconnect()

    print(f"Processing {len(raw_messages)} messages...")
    failed = 0
    quarantined = 0
    duplicates = 0
    processed = 0
    for raw in raw_messages:
        result = pipeline.process_email(raw)
        if result.status == ResultStatus.PROCESSED:
            processed += 1
            payload = result.data
            print(
                f"  [+] {payload['message_key']} | {payload['actor']} | "
                f"{payload['route']} | {payload['subject'][:50]}"
            )
        elif result.status == ResultStatus.DUPLICATE:
            duplicates += 1
            print("  [~] Duplicate skipped")
        elif result.status == ResultStatus.REJECTED_POLICY:
            quarantined += 1
            print(f"  [!] Quarantined: {result.reason}")
        else:
            failed += 1
            print(f"  [x] Runtime failure: {result.reason}")

    print(f"\nDone. {processed} new records ingested.")
    print(f"Duplicates: {duplicates}")
    print(f"Quarantined: {quarantined}")
    print(f"Failed:      {failed}")
    print(f"Seen registry total: {pipeline.seen.count()}")
    print(f"Tail hash: {pipeline.control.get_tail_hash()}")

    if pipeline.processed:
        json_path = pipeline.export_json()
        md_path = pipeline.export_markdown_summary()
        print(f"\nExports:")
        print(f"  JSON: {json_path}")
        print(f"  MD:   {md_path}")


def cmd_ingest_dir(args, config):
    pipeline = _build_pipeline(config)
    results = pipeline.process_directory(args.dir)
    print(f"Processed {len(results)} .eml files from {args.dir}")
    print(f"Deduplicated this run: {pipeline.duplicate_count}")
    print(f"Runtime failures: {pipeline.failed_count}")
    if results:
        json_path = pipeline.export_json()
        md_path = pipeline.export_markdown_summary()
        print(f"Exports: {json_path}, {md_path}")


def cmd_import_drafts(args, config):
    if not config["password"]:
        print("ERROR: Proton IMAP password not set in env, .env, or --config file.", file=sys.stderr)
        sys.exit(1)

    use_ssl = config["use_ssl"] if config.get("use_ssl") else (config["port"] == 993)
    connector = ProtonMailConnector(
        email=config["email"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
        use_ssl=use_ssl,
    )

    drafts_dir = Path(args.dir)
    if not drafts_dir.exists() or not drafts_dir.is_dir():
        print(f"ERROR: Draft directory not found: {drafts_dir}", file=sys.stderr)
        sys.exit(1)

    eml_files = sorted(Path(p) for p in glob(str(drafts_dir / "*.eml")))
    if not eml_files:
        print(f"No .eml files found in {drafts_dir}")
        return

    print(
        f"Connecting to ProtonMail IMAP "
        f"({config['host']}:{config['port']}, target mailbox={args.mailbox})..."
    )
    try:
        connector.connect()
        if args.list_mailboxes:
            print("Available mailboxes:")
            for box in connector.list_mailboxes():
                print(f"  - {box}")

        if args.dry_run:
            print("Dry run enabled. Would append:")
            for p in eml_files:
                print(f"  - {p}")
            return

        imported = 0
        failed = 0
        for path in eml_files:
            raw = path.read_bytes()
            ok = connector.append_message(mailbox=args.mailbox, raw_message=raw, seen=False)
            if ok:
                imported += 1
                print(f"  [+] Appended draft: {path.name}")
            else:
                failed += 1
                print(f"  [x] Failed append: {path.name}")

        print("\nDraft import complete.")
        print(f"Imported: {imported}")
        print(f"Failed:   {failed}")
    except ConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        connector.disconnect()


def cmd_verify_chain(args, config):
    pipeline = _build_pipeline(config)
    report = pipeline.control.verify_chain()
    print("=" * 60)
    print("CHAIN INTEGRITY REPORT")
    print("=" * 60)
    print(f"Total records: {report['total_records']}")
    print(f"Tail hash:     {report['tail_hash']}")
    print(f"Integrity:     {'PASS ✓' if report['integrity_pass'] else 'FAIL ✗'}")
    if report["mismatches"]:
        print(f"\nMismatches found: {len(report['mismatches'])}")
        for m in report["mismatches"]:
            print(f"  Record {m['id']}: {m['field']} mismatch")
    else:
        print("No mismatches detected.")
    print("=" * 60)

    if not report["integrity_pass"]:
        sys.exit(2)


def cmd_export_json(args, config):
    pipeline = _build_pipeline(config)
    path = pipeline.export_json()
    print(f"Exported: {path}")


def cmd_export_md(args, config):
    pipeline = _build_pipeline(config)
    path = pipeline.export_markdown_summary()
    print(f"Exported: {path}")


def cmd_demo(args, config):
    from email.message import EmailMessage
    from email.policy import default

    pipeline = _build_pipeline(config)

    msg1 = EmailMessage(policy=default)
    msg1["Message-ID"] = "<employer-pressure-20260501@clientglobal.com>"
    msg1["Subject"] = "Required: Vacation Selection and Position Confirmation"
    msg1["From"] = "HR Operations <hr.operations@example.com>"
    msg1["To"] = config["email"]
    msg1["Date"] = "Thu, 1 May 2026 09:15:00 -0400"
    msg1.set_content(
        """
Dear Employee,

As part of your return-to-work planning, you are required to submit your
vacation preferences for the 2026-2027 calendar year no later than May 15.

Additionally, please confirm your position selection. Failure to respond
will be considered as acceptance of the default assignment.

This is mandatory and without exception. Consequences of non-response may
include disciplinary review.

Regards,
HR Operations
Client Company Beverage Company
"""
    )

    msg2 = EmailMessage(policy=default)
    msg2["Message-ID"] = "<union-update-20260501@union501.ca>"
    msg2["Subject"] = "Re: Your grievance file next steps"
    msg2["From"] = "Union 501 <delegate@union501.ca>"
    msg2["To"] = config["email"]
    msg2["Date"] = "Thu, 1 May 2026 14:30:00 -0400"
    msg2.set_content(
        """
Hello,

Following our discussion, the union has reviewed your file.
We will schedule a meeting with the employer next week.
Please confirm your availability.

Your delegate,
Union 501
"""
    )

    msg3 = EmailMessage(policy=default)
    msg3["Message-ID"] = "<medical-note-20260428@clinique.axion>"
    msg3["Subject"] = "Medical certificate follow-up"
    msg3["From"] = "Dr. A. Médicale <dr.medicale@clinique.axion>"
    msg3["To"] = config["email"]
    msg3["Date"] = "Mon, 28 Apr 2026 10:00:00 -0400"
    msg3.set_content(
        """
Bonjour,

Veuillez trouver ci-joint votre note médicale prolongée.
Conserver ce document confidentiel.

Dr. A. Médicale
Clinique Axion
"""
    )

    emails = [msg1.as_bytes(), msg2.as_bytes(), msg3.as_bytes()]
    labels = ["EMPLOYER PRESSURE", "UNION", "MEDICAL"]

    print("=" * 60)
    print("DEMO RUN Processing 3 simulated emails")
    print("=" * 60)

    for raw, label in zip(emails, labels):
        result = pipeline.process_email(raw)
        if result.status == ResultStatus.PROCESSED:
            payload = result.data
            print(f"\n[{label}]")
            print(f"  Key:      {payload['message_key']}")
            print(f"  Actor:    {payload['actor']}")
            print(f"  Labels:   {', '.join(payload['labels'])}")
            print(f"  Route:    {payload['route']}")
            print(f"  Policy:   {payload['policy']['reason']}")
            print(f"  SHA256:   {payload['raw_sha256'][:24]}...")
            print(f"  Record:   {payload['record_hash'][:24]}...")
        else:
            print(f"\n[{label}]")
            print(f"  Status:   {result.status.value}")
            print(f"  Reason:   {result.reason}")

    print("\n" + "=" * 60)
    print("EXPORTING")
    print("=" * 60)
    json_path = pipeline.export_json()
    md_path = pipeline.export_markdown_summary()
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")

    print("\n" + "=" * 60)
    print("CHAIN VERIFICATION")
    print("=" * 60)
    report = pipeline.control.verify_chain()
    print(f"Records:   {report['total_records']}")
    print(f"Integrity: {'PASS ✓' if report['integrity_pass'] else 'FAIL ✗'}")
    print(f"Tail:      {report['tail_hash'][:32]}...")


def cmd_register_send(args, config):
    pipeline = _build_pipeline(config)
    from .outbound import DocumentType, SendMethod

    send = pipeline.outbound.register_send(
        actor=args.actor,
        document_type=DocumentType(args.doc_type),
        document_path=args.doc_path,
        send_method=SendMethod(args.method),
        sender_address=args.sender,
        recipient_address=args.recipient,
        tracking_number=args.tracking,
        response_deadline_days=args.deadline_days,
        notes=args.notes,
    )
    print("Registered outbound send (administrative record only)")
    print(f"  Send ID:    {send.send_id}")
    print(f"  Actor:      {send.actor}")
    print(f"  Type:       {send.document_type.value}")
    print(f"  Method:     {send.send_method.value}")
    print(f"  Hash:       {send.document_hash}")
    print(f"  Chain:      {send.chain_record_hash}")
    print(f"  Deadline:   {send.response_deadline}")
    print("  Note:       This is not legal service proof or legal filing confirmation.")


def cmd_confirm_delivery(args, config):
    pipeline = _build_pipeline(config)
    pipeline.outbound.confirm_delivery(args.send_id, args.proof_path)
    print(f"Delivery confirmed for send {args.send_id}")
    print(f"  Proof: {args.proof_path}")


def cmd_pending(args, config):
    pipeline = _build_pipeline(config)
    pending = pipeline.outbound.get_pending()
    print(f"Pending sends: {len(pending)}")
    for p in pending:
        status = "awaiting delivery" if not p.get("delivery_date") else "awaiting response"
        print(f"  {p['send_id']} | {p['actor']} | {p['document_type']} | {status}")


def cmd_export_outbound(args, config):
    pipeline = _build_pipeline(config)
    path = str(Path(config["output_dir"]) / f"{config['dossier_id']}_outbound_manifest.json")
    pipeline.outbound.export_manifest(path)
    print(f"Exported administrative outbound manifest: {path}")


def main():
    parser = argparse.ArgumentParser(description="Dossier DOSSIER-PIPELINE Evidence Governance Pipeline")
    parser.add_argument("--config", default=None, help="Path to JSON config file")
    parser.add_argument("--dossier", default=None, help="Dossier ID")
    parser.add_argument("--output-dir", default=None, help="Output directory")

    sub = parser.add_subparsers(dest="command")

    p_ingest = sub.add_parser("ingest-proton", help="Ingest from ProtonMail IMAP")
    p_ingest.add_argument("--limit", type=int, default=None, help="Max messages to fetch")

    p_dir = sub.add_parser("ingest-dir", help="Ingest .eml files from directory")
    p_dir.add_argument("dir", help="Directory containing .eml files")

    p_import = sub.add_parser("import-drafts", help="Import local .eml files into Proton mailbox via IMAP APPEND")
    p_import.add_argument("--dir", required=True, help="Directory containing .eml draft files")
    p_import.add_argument("--mailbox", default="Drafts", help="Target IMAP mailbox name")
    p_import.add_argument("--dry-run", action="store_true", help="Preview files without appending")
    p_import.add_argument("--list-mailboxes", action="store_true", help="List visible IMAP mailboxes before import")

    p_audit = sub.add_parser("audit-actors", help="Audit sent vs inbox response status for core dossier actors")
    p_audit.add_argument("--limit", type=int, default=500, help="Max messages per mailbox to analyze")
    p_audit.add_argument("--mailboxes", default="INBOX,Sent", help="Comma-separated mailbox list")
    p_audit.add_argument("--write-json", action="store_true", help="Write JSON report into output_dir")

    p_send = sub.add_parser("register-send", help="Register an outbound send")
    p_send.add_argument("--actor", required=True, help="Target actor (employer/insurer/union/medical/psychologist)")
    p_send.add_argument("--doc-type", required=True, help="Document type (litigation_hold/demand_letter/grievance/formal_reply/medical_request/insurer_notice/union_notice)")
    p_send.add_argument("--doc-path", required=True, help="Path to document file")
    p_send.add_argument("--method", default="registered_mail", help="Send method")
    p_send.add_argument("--sender", required=True, help="Your address")
    p_send.add_argument("--recipient", required=True, help="Recipient address")
    p_send.add_argument("--tracking", help="Tracking or bailiff number")
    p_send.add_argument("--deadline-days", type=int, default=30, help="Response deadline in days")
    p_send.add_argument("--notes", default="", help="Notes")

    p_deliver = sub.add_parser("confirm-delivery", help="Confirm delivery of outbound send")
    p_deliver.add_argument("--send-id", required=True, help="Send ID")
    p_deliver.add_argument("--proof-path", required=True, help="Path to delivery proof (AR receipt / constat)")

    p_pending = sub.add_parser("pending", help="List pending outbound sends")
    sub.add_parser("export-outbound", help="Export outbound manifest")

    sub.add_parser("verify-chain", help="Verify hash chain integrity")
    sub.add_parser("export-json", help="Export JSON manifest")
    sub.add_parser("export-md", help="Export Markdown summary")
    sub.add_parser("demo", help="Run demo with simulated emails")
    sub.add_parser("enforce", help="Run projection/enforcement summary")
    sub.add_parser("verify", help="Run chain/replay/projection verification")

    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dossier is not None:
        config["dossier_id"] = args.dossier
    if args.output_dir is not None:
        config["output_dir"] = args.output_dir

    if args.command:
        # Say where data will be written, rather than letting the working
        # directory decide silently (audit finding F-11).
        config["output_dir"] = str(_resolve_output_dir(config))
        print(f"Data directory: {config['output_dir']}")

    if args.command == "ingest-proton":
        cmd_ingest_proton(args, config)
    elif args.command == "ingest-dir":
        cmd_ingest_dir(args, config)
    elif args.command == "import-drafts":
        cmd_import_drafts(args, config)
    elif args.command == "audit-actors":
        cmd_audit_actors(args, config)
    elif args.command == "verify-chain":
        cmd_verify_chain(args, config)
    elif args.command == "export-json":
        cmd_export_json(args, config)
    elif args.command == "export-md":
        cmd_export_md(args, config)
    elif args.command == "register-send":
        cmd_register_send(args, config)
    elif args.command == "confirm-delivery":
        cmd_confirm_delivery(args, config)
    elif args.command == "pending":
        cmd_pending(args, config)
    elif args.command == "export-outbound":
        cmd_export_outbound(args, config)
    elif args.command == "demo":
        cmd_demo(args, config)
    elif args.command == "enforce":
        cmd_enforce(args, config)
    elif args.command == "verify":
        cmd_verify(args, config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
