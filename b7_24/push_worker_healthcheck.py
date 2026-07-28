import socket
import sys
from datetime import UTC, datetime

from app import create_app
from app.db import get_client, get_db


def main() -> int:
    app = create_app()
    with app.app_context():
        get_client().admin.command("ping")
        heartbeat = get_db().pushWorkerHeartbeats.find_one(
            {
                "host": socket.gethostname(),
                "status": "running",
                "expiresAt": {"$gt": datetime.now(UTC)},
            }
        )
    return 0 if heartbeat is not None else 1


if __name__ == "__main__":
    sys.exit(main())
