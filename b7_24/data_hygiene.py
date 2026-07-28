from __future__ import annotations

import argparse
import json
import sys

from bson import ObjectId

from app import create_app
from app.db import ensure_indexes, get_db
from app.services.account_deletion import delete_worker_account
from app.services.data_hygiene import (
    build_data_hygiene_report,
    correct_invalid_worker_phone,
    legacy_worker_cleanup_allowed,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    app = create_app()
    try:
        with app.app_context():
            ensure_indexes()
            result = _run_command(get_db(), app.config, args)
    except Exception as error:
        print(
            json.dumps(
                {"status": "failed", "error": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_command(db, config, args) -> dict:
    if args.command == "report":
        return build_data_hygiene_report(
            db,
            employer_key=args.employer_key,
        )

    if not ObjectId.is_valid(args.worker_id):
        raise ValueError("worker-id must be a valid ObjectId")
    worker = db.users.find_one(
        {
            "_id": ObjectId(args.worker_id),
            "employerKey": args.employer_key,
        }
    )
    if worker is None:
        raise ValueError("worker not found for employer")

    if args.command == "correct-phone":
        corrected = correct_invalid_worker_phone(
            db,
            worker,
            args.phone,
        )
        return {
            "status": "corrected",
            "workerId": str(corrected["_id"]),
            "employerKey": corrected.get(
                "employerKey",
                "default",
            ),
        }

    if args.confirmation != "TEMIZLE":
        raise ValueError("confirmation must be TEMIZLE")
    if not legacy_worker_cleanup_allowed(db, worker):
        raise ValueError(
            "worker is not eligible for safe legacy cleanup"
        )
    deletion = delete_worker_account(
        db,
        worker["_id"],
        config["UPLOAD_FOLDER"],
        config["ACCOUNT_DELETION_AUDIT_RETENTION_DAYS"],
    )
    return {
        "status": deletion["status"],
        "workerId": str(worker["_id"]),
        "employerKey": worker.get("employerKey", "default"),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit and remediate invalid legacy worker phones."
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )
    report = subparsers.add_parser(
        "report",
        help="Print a masked, read-only report.",
    )
    report.add_argument("--employer-key")

    correction = subparsers.add_parser(
        "correct-phone",
        help="Correct one unverified legacy phone.",
    )
    _add_worker_arguments(correction)
    correction.add_argument("--phone", required=True)

    cleanup = subparsers.add_parser(
        "cleanup-worker",
        help="Safely remove one eligible legacy worker.",
    )
    _add_worker_arguments(cleanup)
    cleanup.add_argument("--confirmation", required=True)
    return parser


def _add_worker_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--employer-key", required=True)
    parser.add_argument("--worker-id", required=True)


if __name__ == "__main__":
    raise SystemExit(main())
