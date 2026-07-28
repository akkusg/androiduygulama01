from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from werkzeug.exceptions import BadRequest, Conflict, NotFound


COLLECTION_FIELDS = {
    "assessments": "assessments",
    "trainings": "trainings",
    "useful-info": "usefulInfo",
    "qa-knowledge": "qaKnowledgeBase",
    "shuttle-routes": "shuttle.routes",
}

_ITEM_PREFIXES = {
    "assessments": "assessment",
    "trainings": "training",
    "useful-info": "info",
    "qa-knowledge": "qa",
    "shuttle-routes": "route",
}


def normalize_worker_config_patch(payload: dict) -> dict:
    _require_object(payload, "request body")
    allowed_fields = {"assessments", "trainings", "usefulInfo", "shuttle", "qaKnowledgeBase"}
    _reject_unknown_fields(payload, allowed_fields, "worker config")
    if not payload:
        raise BadRequest("At least one worker config field is required")

    normalized = {}
    if "assessments" in payload:
        normalized["assessments"] = _normalize_collection(
            "assessments", payload["assessments"]
        )
    if "trainings" in payload:
        normalized["trainings"] = _normalize_collection(
            "trainings", payload["trainings"]
        )
    if "usefulInfo" in payload:
        normalized["usefulInfo"] = _normalize_collection(
            "useful-info", payload["usefulInfo"]
        )
    if "qaKnowledgeBase" in payload:
        normalized["qaKnowledgeBase"] = _normalize_collection(
            "qa-knowledge", payload["qaKnowledgeBase"]
        )
    if "shuttle" in payload:
        shuttle = _require_object(payload["shuttle"], "shuttle")
        _reject_unknown_fields(
            shuttle, {"enabled", "title", "description", "routes"}, "shuttle"
        )
        normalized["shuttle"] = {
            "enabled": _require_bool(shuttle.get("enabled", False), "shuttle.enabled"),
            "title": _text(
                shuttle.get("title", ""), "shuttle.title", max_length=160
            ),
            "description": _text(
                shuttle.get("description", ""),
                "shuttle.description",
                max_length=1000,
            ),
            "routes": _normalize_collection(
                "shuttle-routes", shuttle.get("routes", [])
            ),
        }
    return normalized


def create_worker_config_item(
    db, config: dict, resource: str, payload: dict
) -> tuple[dict, dict]:
    field = _resource_field(resource)
    item_payload = deepcopy(_require_object(payload, resource))
    item_payload.setdefault("id", _new_item_id(_ITEM_PREFIXES[resource]))
    item = _normalize_item(resource, item_payload)

    if _find_item(_get_nested(config, field, []), item["id"]) is not None:
        raise Conflict(f"{resource} item id already exists")

    now = datetime.now(UTC)
    db.workerSupportConfigs.update_one(
        {"_id": config["_id"]},
        {"$push": {field: item}, "$set": {"updatedAt": now}},
    )
    updated = db.workerSupportConfigs.find_one({"_id": config["_id"]})
    return item, updated


def update_worker_config_item(
    db, config: dict, resource: str, item_id: str, payload: dict
) -> tuple[dict, dict]:
    field = _resource_field(resource)
    normalized_id = _identifier(item_id, f"{resource}.id")
    patch = deepcopy(_require_object(payload, resource))
    _reject_unknown_fields(patch, _allowed_item_fields(resource), resource)
    if "id" in patch and patch["id"] != normalized_id:
        raise BadRequest("Item id cannot be changed")

    current_item = _find_item(_get_nested(config, field, []), normalized_id)
    if current_item is None:
        raise NotFound(f"{resource} item not found")

    item = _normalize_item(
        resource, {**current_item, **patch, "id": normalized_id}
    )
    now = datetime.now(UTC)
    db.workerSupportConfigs.update_one(
        {"_id": config["_id"]},
        {"$set": {f"{field}.$[item]": item, "updatedAt": now}},
        array_filters=[{"item.id": normalized_id}],
    )
    updated = db.workerSupportConfigs.find_one({"_id": config["_id"]})
    return item, updated


def delete_worker_config_item(
    db, config: dict, resource: str, item_id: str
) -> dict:
    field = _resource_field(resource)
    normalized_id = _identifier(item_id, f"{resource}.id")
    if _find_item(_get_nested(config, field, []), normalized_id) is None:
        raise NotFound(f"{resource} item not found")

    result = db.workerSupportConfigs.update_one(
        {"_id": config["_id"]},
        {
            "$pull": {field: {"id": normalized_id}},
            "$set": {"updatedAt": datetime.now(UTC)},
        },
    )
    if result.modified_count == 0:
        raise NotFound(f"{resource} item not found")
    return db.workerSupportConfigs.find_one({"_id": config["_id"]})


def update_shuttle_settings(db, config: dict, payload: dict) -> dict:
    patch = _require_object(payload, "shuttle")
    allowed_fields = {"enabled", "title", "description"}
    _reject_unknown_fields(patch, allowed_fields, "shuttle")
    if not patch:
        raise BadRequest("At least one shuttle field is required")

    current = deepcopy(config.get("shuttle") or {})
    if "enabled" in patch:
        current["enabled"] = _require_bool(patch["enabled"], "shuttle.enabled")
    if "title" in patch:
        current["title"] = _text(
            patch["title"], "shuttle.title", required=True, max_length=160
        )
    if "description" in patch:
        current["description"] = _text(
            patch["description"], "shuttle.description", max_length=1000
        )
    current.setdefault("routes", [])

    db.workerSupportConfigs.update_one(
        {"_id": config["_id"]},
        {
            "$set": {
                "shuttle": current,
                "updatedAt": datetime.now(UTC),
            }
        },
    )
    return db.workerSupportConfigs.find_one({"_id": config["_id"]})


def _normalize_collection(resource: str, raw_items) -> list[dict]:
    if not isinstance(raw_items, list):
        raise BadRequest(f"{resource} must be an array")
    if len(raw_items) > 100:
        raise BadRequest(f"{resource} cannot contain more than 100 items")

    items = []
    item_ids = set()
    for raw_item in raw_items:
        item_payload = deepcopy(_require_object(raw_item, f"{resource} item"))
        item_payload.setdefault("id", _new_item_id(_ITEM_PREFIXES[resource]))
        item = _normalize_item(resource, item_payload)
        if item["id"] in item_ids:
            raise BadRequest(f"Duplicate {resource} item id: {item['id']}")
        item_ids.add(item["id"])
        items.append(item)
    return items


def _normalize_item(resource: str, payload: dict) -> dict:
    _reject_unknown_fields(payload, _allowed_item_fields(resource), resource)
    if resource == "assessments":
        return _normalize_assessment(payload)
    if resource == "trainings":
        return _normalize_training(payload)
    if resource == "useful-info":
        return _normalize_useful_info(payload)
    if resource == "qa-knowledge":
        return _normalize_qa_knowledge(payload)
    if resource == "shuttle-routes":
        return _normalize_shuttle_route(payload)
    raise NotFound("Worker config resource not found")


def _normalize_assessment(payload: dict) -> dict:
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        raise BadRequest("assessment.questions must contain at least one question")
    if len(questions) > 50:
        raise BadRequest("assessment.questions cannot contain more than 50 items")

    normalized_questions = []
    question_ids = set()
    for raw_question in questions:
        question = _require_object(raw_question, "assessment question")
        _reject_unknown_fields(
            question, {"id", "prompt", "options"}, "assessment question"
        )
        question_id = _identifier(question.get("id"), "assessment question.id")
        if question_id in question_ids:
            raise BadRequest(f"Duplicate assessment question id: {question_id}")
        question_ids.add(question_id)

        options = question.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise BadRequest(
                "assessment question.options must contain at least two options"
            )
        if len(options) > 20:
            raise BadRequest(
                "assessment question.options cannot contain more than 20 items"
            )

        normalized_options = []
        option_ids = set()
        for raw_option in options:
            option = _require_object(raw_option, "assessment option")
            _reject_unknown_fields(
                option, {"id", "label", "score"}, "assessment option"
            )
            option_id = _identifier(option.get("id"), "assessment option.id")
            if option_id in option_ids:
                raise BadRequest(
                    f"Duplicate assessment option id: {option_id}"
                )
            option_ids.add(option_id)
            normalized_options.append(
                {
                    "id": option_id,
                    "label": _text(
                        option.get("label"),
                        "assessment option.label",
                        required=True,
                        max_length=300,
                    ),
                    "score": _bounded_int(
                        option.get("score"),
                        "assessment option.score",
                        minimum=0,
                        maximum=100,
                    ),
                }
            )

        normalized_questions.append(
            {
                "id": question_id,
                "prompt": _text(
                    question.get("prompt"),
                    "assessment question.prompt",
                    required=True,
                    max_length=500,
                ),
                "options": normalized_options,
            }
        )

    return {
        "id": _identifier(payload.get("id"), "assessment.id"),
        "title": _text(
            payload.get("title"), "assessment.title", required=True, max_length=160
        ),
        "description": _text(
            payload.get("description", ""),
            "assessment.description",
            max_length=1000,
        ),
        "status": _enum(
            payload.get("status", "available"),
            "assessment.status",
            {"available", "draft", "archived"},
        ),
        "durationMinutes": _bounded_int(
            payload.get("durationMinutes"),
            "assessment.durationMinutes",
            minimum=1,
            maximum=480,
        ),
        "required": _require_bool(
            payload.get("required", False), "assessment.required"
        ),
        "passScore": _bounded_int(
            payload.get("passScore", 70),
            "assessment.passScore",
            minimum=0,
            maximum=100,
        ),
        "questions": normalized_questions,
    }


def _normalize_training(payload: dict) -> dict:
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules:
        raise BadRequest("training.modules must contain at least one module")
    if len(modules) > 100:
        raise BadRequest("training.modules cannot contain more than 100 items")

    normalized_modules = []
    module_ids = set()
    for raw_module in modules:
        module = _require_object(raw_module, "training module")
        _reject_unknown_fields(
            module, {"id", "title", "body"}, "training module"
        )
        module_id = _identifier(module.get("id"), "training module.id")
        if module_id in module_ids:
            raise BadRequest(f"Duplicate training module id: {module_id}")
        module_ids.add(module_id)
        normalized_modules.append(
            {
                "id": module_id,
                "title": _text(
                    module.get("title"),
                    "training module.title",
                    required=True,
                    max_length=160,
                ),
                "body": _text(
                    module.get("body"),
                    "training module.body",
                    required=True,
                    max_length=10000,
                ),
            }
        )

    return {
        "id": _identifier(payload.get("id"), "training.id"),
        "title": _text(
            payload.get("title"), "training.title", required=True, max_length=160
        ),
        "description": _text(
            payload.get("description", ""),
            "training.description",
            max_length=1000,
        ),
        "durationMinutes": _bounded_int(
            payload.get("durationMinutes"),
            "training.durationMinutes",
            minimum=1,
            maximum=1440,
        ),
        "status": _enum(
            payload.get("status", "available"),
            "training.status",
            {"available", "draft", "archived"},
        ),
        "modules": normalized_modules,
    }


def _normalize_useful_info(payload: dict) -> dict:
    return {
        "id": _identifier(payload.get("id"), "usefulInfo.id"),
        "title": _text(
            payload.get("title"), "usefulInfo.title", required=True, max_length=160
        ),
        "body": _text(
            payload.get("body"),
            "usefulInfo.body",
            required=True,
            max_length=10000,
        ),
        "category": _text(
            payload.get("category", "general"),
            "usefulInfo.category",
            required=True,
            max_length=80,
        ),
    }


def _normalize_qa_knowledge(payload: dict) -> dict:
    keywords = payload.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        raise BadRequest("qaKnowledge.keywords must contain at least one keyword")
    if len(keywords) > 30:
        raise BadRequest("qaKnowledge.keywords cannot contain more than 30 items")

    normalized_keywords = []
    seen = set()
    for keyword in keywords:
        value = _text(
            keyword,
            "qaKnowledge.keyword",
            required=True,
            max_length=80,
        )
        normalized = value.casefold()
        if normalized not in seen:
            normalized_keywords.append(value)
            seen.add(normalized)

    return {
        "id": _identifier(payload.get("id"), "qaKnowledge.id"),
        "keywords": normalized_keywords,
        "answer": _text(
            payload.get("answer"),
            "qaKnowledge.answer",
            required=True,
            max_length=4000,
        ),
    }


def _normalize_shuttle_route(payload: dict) -> dict:
    return {
        "id": _identifier(payload.get("id"), "shuttleRoute.id"),
        "name": _text(
            payload.get("name"),
            "shuttleRoute.name",
            required=True,
            max_length=160,
        ),
        "pickupWindow": _text(
            payload.get("pickupWindow"),
            "shuttleRoute.pickupWindow",
            required=True,
            max_length=120,
        ),
    }


def _allowed_item_fields(resource: str) -> set[str]:
    fields = {
        "assessments": {
            "id",
            "title",
            "description",
            "status",
            "durationMinutes",
            "required",
            "passScore",
            "questions",
        },
        "trainings": {
            "id",
            "title",
            "description",
            "durationMinutes",
            "status",
            "modules",
        },
        "useful-info": {"id", "title", "body", "category"},
        "qa-knowledge": {"id", "keywords", "answer"},
        "shuttle-routes": {"id", "name", "pickupWindow"},
    }
    if resource not in fields:
        raise NotFound("Worker config resource not found")
    return fields[resource]


def _resource_field(resource: str) -> str:
    field = COLLECTION_FIELDS.get(resource)
    if field is None:
        raise NotFound("Worker config resource not found")
    return field


def _get_nested(document: dict, path: str, default):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _find_item(items: list[dict], item_id: str) -> dict | None:
    return next((item for item in items if item.get("id") == item_id), None)


def _new_item_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _require_object(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise BadRequest(f"{field} must be an object")
    return value


def _reject_unknown_fields(
    payload: dict, allowed_fields: set[str], field: str
) -> None:
    unknown = sorted(set(payload) - allowed_fields)
    if unknown:
        raise BadRequest(f"Unknown {field} field(s): {', '.join(unknown)}")


def _identifier(value, field: str) -> str:
    identifier = _text(value, field, required=True, max_length=80)
    if not all(char.isalnum() or char in {"-", "_", "."} for char in identifier):
        raise BadRequest(
            f"{field} may contain only letters, numbers, hyphens, underscores, and dots"
        )
    return identifier


def _text(
    value,
    field: str,
    *,
    required: bool = False,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise BadRequest(f"{field} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise BadRequest(f"{field} cannot be empty")
    if len(normalized) > max_length:
        raise BadRequest(f"{field} cannot exceed {max_length} characters")
    return normalized


def _bounded_int(value, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise BadRequest(f"{field} must be between {minimum} and {maximum}")
    return value


def _require_bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise BadRequest(f"{field} must be a boolean")
    return value


def _enum(value, field: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise BadRequest(f"{field} must be one of: {', '.join(sorted(choices))}")
    return value
