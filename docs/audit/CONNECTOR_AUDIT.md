# Connector Audit

```python
def upload_evidence(
    case_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    case = find_case(db, case_id)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or "\x00" in filename or len(filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "INVALID_FILENAME",
                "message": "Upload a file with a valid name of at most 255 characters.",
            },
        )

    storage_key = uuid.uuid4().hex
    temporary_path: Path | None = None
    stored_file = storage_root / f"{storage_key}.bin"
    digest = hashlib.sha256()
    byte_size = 0
    try:
        storage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".upload-",
            dir=storage_root,
            delete=False,
        ) as destination:
            temporary_path = Path(destination.name)
            while chunk := file.file.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
                byte_size += len(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, stored_file)
        temporary_path = None

        content_hash = digest.hexdigest()
        duplicate = db.scalar(
            select(Document.id).where(
                Document.case_id == case.id,
                Document.content_hash == content_hash,
            )
        ) is not None
        document = Document(
            case_id=case.id,
            document_key=f"E-{storage_key}",
            filename=filename,
            content_hash=content_hash,
            storage_key=storage_key,
            media_type=file.content_type or "application/octet-stream",
            byte_size=byte_size,
        )
        db.add(document)
        db.flush()
        _custody_log(
            db,
            case_id=case.id,
            evidence_id=document.document_key,
            action="evidence_uploaded",
        )
        # The bytes and their custody row are committed before analysis
        # runs, so an analysis failure can never lose an accepted upload.
        db.commit()

        run_analysis(document)
        _custody_log(
            db,
            case_id=case.id,
            evidence_id=document.document_key,
            action="evidence_analysed",
        )
        db.commit()
        return {
            "id": document.document_key,
            "hash": content_hash,
            # The same value the pipeline records as `source_sha256`, so the
            # product path and the pipeline path bind the same artifact.
            "sourceSha256": content_hash,
            "duplicate": duplicate,
            "processingStatus": document.extract_status,
            # The same compact analysis view the evidence item carries, so
            # the intake screen can say *why* an artifact was not read
            # rather than only that it was not.
            "analysis": _analysis_summary(document),
        }
    except OSError:
        db.rollback()
        stored_file.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail={
                "error": "EVIDENCE_STORAGE_FAILED",
                "message": "The local evidence file could not be stored.",
            },
        ) from None
    except SQLAlchemyError:
        db.rollback()
        stored_file.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "EVIDENCE_METADATA_FAILED",
                "message": "The local evidence metadata could not be saved.",
            },
        ) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
```
