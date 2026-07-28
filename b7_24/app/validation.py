from werkzeug.exceptions import BadRequest


def require_json_fields(payload: dict, fields: list[str]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise BadRequest(f"Missing required field(s): {', '.join(missing)}")


def parse_pagination(
    args, *, default_limit: int = 25, maximum_limit: int = 100
) -> tuple[int, int]:
    try:
        page = max(1, int(args.get("page", "1")))
        limit = min(
            maximum_limit,
            max(1, int(args.get("limit", str(default_limit)))),
        )
    except (TypeError, ValueError) as error:
        raise BadRequest("page and limit must be integers") from error
    return page, limit
