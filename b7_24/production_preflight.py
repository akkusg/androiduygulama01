from __future__ import annotations

import json
import sys

from app import create_app
from app.services.production_preflight import (
    run_production_preflight,
)


def main() -> int:
    try:
        result = run_production_preflight(create_app())
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
