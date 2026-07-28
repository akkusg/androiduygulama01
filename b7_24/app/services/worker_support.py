from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from bson import ObjectId
from werkzeug.exceptions import BadRequest, Conflict


DEFAULT_EMPLOYER_KEY = "default"
WORKER_SUPPORT_SCHEMA_VERSION = 2

DEFAULT_WORKER_SUPPORT_CONFIG = {
    "employerKey": DEFAULT_EMPLOYER_KEY,
    "assessments": [
        {
            "id": "safety-readiness",
            "title": "İş Güvenliği Hazırlık Değerlendirmesi",
            "description": "Temel güvenlik, vardiya uyumu ve saha kurallarını ölçer.",
            "status": "available",
            "durationMinutes": 12,
            "required": True,
            "passScore": 70,
            "questions": [
                {
                    "id": "ppe-check",
                    "prompt": "Sahaya girmeden önce hangi ekipmanları kontrol edersin?",
                    "options": [
                        {"id": "ppe-complete", "label": "Baret, yelek ve iş ayakkabısı", "score": 50},
                        {"id": "personal-items", "label": "Telefon ve kişisel eşyalar", "score": 0},
                    ],
                },
                {
                    "id": "unsafe-condition",
                    "prompt": "Güvensiz bir durum görürsen ne yaparsın?",
                    "options": [
                        {"id": "notify-supervisor", "label": "İşi durdurup sorumluya bildiririm", "score": 50},
                        {"id": "continue-work", "label": "İşi aksatmamak için devam ederim", "score": 0},
                    ],
                },
            ],
        },
        {
            "id": "role-fit",
            "title": "Rol Uygunluğu Değerlendirmesi",
            "description": "Beceri, deneyim ve çalışma tercihlerini iş beklentileriyle eşleştirir.",
            "status": "available",
            "durationMinutes": 8,
            "required": False,
            "passScore": 60,
            "questions": [
                {
                    "id": "shift-fit",
                    "prompt": "Vardiyalı çalışma düzenine yaklaşımın nedir?",
                    "options": [
                        {"id": "shift-ready", "label": "Vardiyalı çalışabilirim", "score": 50},
                        {"id": "day-only", "label": "Sadece gündüz çalışabilirim", "score": 25},
                    ],
                },
                {
                    "id": "team-fit",
                    "prompt": "Ekip içinde görev paylaşımı olduğunda nasıl ilerlersin?",
                    "options": [
                        {"id": "team-communicate", "label": "Sorumlulukları netleştirip iletişim kurarım", "score": 50},
                        {"id": "solo-work", "label": "Kendi işime odaklanırım", "score": 20},
                    ],
                },
            ],
        },
    ],
    "trainings": [
        {
            "id": "isg-101",
            "title": "Temel İSG Eğitimi",
            "description": "Saha güvenliği, ekipman kullanımı ve acil durum adımları.",
            "durationMinutes": 25,
            "status": "available",
            "modules": [
                {
                    "id": "ppe",
                    "title": "Kişisel koruyucu ekipman",
                    "body": "Baret, reflektif yelek, iş ayakkabısı ve görevine uygun eldiven sahaya girişten önce kontrol edilir.",
                },
                {
                    "id": "emergency",
                    "title": "Acil durum adımları",
                    "body": "Kaza, yangın veya tehlikeli durumlarda işi durdur, güvenli alana geç ve vardiya sorumlusuna haber ver.",
                },
            ],
        },
        {
            "id": "shift-onboarding",
            "title": "Vardiya ve Devam Kuralları",
            "description": "Giriş-çıkış, mola ve devamsızlık bildirimleri.",
            "durationMinutes": 10,
            "status": "available",
            "modules": [
                {
                    "id": "attendance",
                    "title": "Devam bildirimi",
                    "body": "Vardiya başlangıcından önce girişini tamamla; gelemeyeceksen operasyon sorumlusuna önceden bilgi ver.",
                },
                {
                    "id": "breaks",
                    "title": "Mola düzeni",
                    "body": "Mola saatleri ekip planına göre kullanılır ve üretim alanı güvenli bırakılarak çıkılır.",
                },
            ],
        },
    ],
    "usefulInfo": [
        {
            "id": "first-day",
            "title": "İlk Gün Bilgileri",
            "body": "Kimlik, banka bilgisi ve varsa sertifikalarını yanında getir.",
            "category": "onboarding",
        },
        {
            "id": "payroll",
            "title": "Ödeme ve Puantaj",
            "body": "Puantaj haftalık kontrol edilir; eksik günleri vardiya sorumlusuna bildir.",
            "category": "payroll",
        },
    ],
    "shuttle": {
        "enabled": True,
        "title": "Servis Planlama",
        "description": "Servis ihtiyacını ve durak tercihini bildir.",
        "routes": [
            {"id": "route-1", "name": "Merkez - OSB", "pickupWindow": "07:00 - 07:30"},
            {"id": "route-2", "name": "Kartal - Gebze", "pickupWindow": "06:45 - 07:20"},
        ],
    },
    "qaKnowledgeBase": [
        {
            "id": "shuttle-help",
            "keywords": ["servis", "shuttle", "durak", "ulaşım", "ulasim"],
            "answer": "Servis için tercih ettiğin güzergahı uygulamadaki Servis Planlama bölümünden bildir.",
        },
        {
            "id": "payroll-help",
            "keywords": ["maaş", "maas", "ödeme", "odeme", "puantaj"],
            "answer": "Ödeme ve puantaj bilgileri haftalık kontrol edilir; eksik günleri vardiya sorumlusuna ilet.",
        },
        {
            "id": "training-help",
            "keywords": ["eğitim", "egitim", "sertifika", "isg"],
            "answer": "Zorunlu eğitimleri işe başlamadan önce tamamlaman gerekir; İSG eğitimi önceliklidir.",
        },
        {
            "id": "shift-help",
            "keywords": ["vardiya", "mesai", "izin"],
            "answer": "Vardiya veya izin değişikliği için en geç bir gün önce operasyon sorumlusuna haber ver.",
        },
    ],
}


def get_or_create_worker_support_config(db, employer_key: str | None = None) -> dict:
    key = employer_key or DEFAULT_EMPLOYER_KEY
    config = db.workerSupportConfigs.find_one({"employerKey": key})
    if config:
        if config.get("schemaVersion", 0) < WORKER_SUPPORT_SCHEMA_VERSION:
            config = _backfill_worker_support_item_ids(db, config)
        if (
            key == DEFAULT_EMPLOYER_KEY
            and config.get("schemaVersion", 0) < WORKER_SUPPORT_SCHEMA_VERSION
        ):
            config = _backfill_default_worker_support_config(db, config)
        if config.get("schemaVersion", 0) < WORKER_SUPPORT_SCHEMA_VERSION:
            db.workerSupportConfigs.update_one(
                {"_id": config["_id"]},
                {
                    "$set": {
                        "schemaVersion": WORKER_SUPPORT_SCHEMA_VERSION,
                        "updatedAt": datetime.now(UTC),
                    }
                },
            )
            config = db.workerSupportConfigs.find_one({"_id": config["_id"]})
        return config

    now = datetime.now(UTC)
    doc = {
        **deepcopy(DEFAULT_WORKER_SUPPORT_CONFIG),
        "employerKey": key,
        "schemaVersion": WORKER_SUPPORT_SCHEMA_VERSION,
        "createdAt": now,
        "updatedAt": now,
    }
    result = db.workerSupportConfigs.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def upsert_worker_support_config(db, employer_key: str, payload: dict) -> dict:
    now = datetime.now(UTC)
    current = get_or_create_worker_support_config(db, employer_key)
    allowed_fields = ["assessments", "trainings", "usefulInfo", "shuttle", "qaKnowledgeBase"]
    updated = {field: payload[field] for field in allowed_fields if field in payload}
    updated["updatedAt"] = now
    db.workerSupportConfigs.update_one({"_id": current["_id"]}, {"$set": updated})
    return db.workerSupportConfigs.find_one({"_id": current["_id"]})


def build_worker_support_assignments(db, user: dict) -> dict:
    employer_key = user.get("employerKey") or DEFAULT_EMPLOYER_KEY
    config = get_or_create_worker_support_config(db, employer_key)
    assessment_catalog = _available_items(
        config.get("assessments", [])
    )
    training_catalog = _available_items(config.get("trainings", []))
    assignment = db.workerSupportAssignments.find_one(
        {
            "userId": user["_id"],
            "employerKey": employer_key,
        }
    )
    return {
        "workerId": str(user["_id"]),
        "employerKey": employer_key,
        "customized": assignment is not None,
        "assessmentIds": _selected_assignment_ids(
            assignment,
            "assessmentIds",
            assessment_catalog,
        ),
        "trainingIds": _selected_assignment_ids(
            assignment,
            "trainingIds",
            training_catalog,
        ),
        "catalog": {
            "assessments": [
                _assignment_catalog_item(item)
                for item in assessment_catalog
            ],
            "trainings": [
                _assignment_catalog_item(item)
                for item in training_catalog
            ],
        },
        "createdAt": assignment.get("createdAt") if assignment else None,
        "updatedAt": assignment.get("updatedAt") if assignment else None,
    }


def save_worker_support_assignments(
    db,
    user: dict,
    payload: dict,
    assigned_by: str | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    allowed_fields = {"assessmentIds", "trainingIds"}
    unknown_fields = set(payload) - allowed_fields
    if unknown_fields:
        raise BadRequest(
            "Unknown worker support assignment fields: "
            + ", ".join(sorted(unknown_fields))
        )
    missing_fields = allowed_fields - set(payload)
    if missing_fields:
        raise BadRequest(
            "Missing worker support assignment fields: "
            + ", ".join(sorted(missing_fields))
        )

    employer_key = user.get("employerKey") or DEFAULT_EMPLOYER_KEY
    config = get_or_create_worker_support_config(db, employer_key)
    assessment_catalog = _available_items(
        config.get("assessments", [])
    )
    training_catalog = _available_items(config.get("trainings", []))
    assessment_ids = _normalize_assignment_ids(
        payload["assessmentIds"],
        "assessmentIds",
        assessment_catalog,
    )
    training_ids = _normalize_assignment_ids(
        payload["trainingIds"],
        "trainingIds",
        training_catalog,
    )
    now = datetime.now(UTC)
    db.workerSupportAssignments.update_one(
        {
            "userId": user["_id"],
            "employerKey": employer_key,
        },
        {
            "$set": {
                "assessmentIds": assessment_ids,
                "trainingIds": training_ids,
                "assignedBy": assigned_by,
                "updatedAt": now,
            },
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    return build_worker_support_assignments(db, user)


def build_worker_hub(db, user: dict) -> dict:
    employer_key = user.get("employerKey") or DEFAULT_EMPLOYER_KEY
    config = get_or_create_worker_support_config(db, employer_key)
    assessment_catalog = _available_items(
        config.get("assessments", [])
    )
    training_catalog = _available_items(config.get("trainings", []))
    assignment = db.workerSupportAssignments.find_one(
        {
            "userId": user["_id"],
            "employerKey": employer_key,
        }
    )
    assigned_assessment_ids = set(
        _selected_assignment_ids(
            assignment,
            "assessmentIds",
            assessment_catalog,
        )
    )
    assigned_training_ids = set(
        _selected_assignment_ids(
            assignment,
            "trainingIds",
            training_catalog,
        )
    )
    assessment_results = {
        item["assessmentId"]: item
        for item in db.workerAssessmentResults.find({"userId": user["_id"]})
    }
    training_progress = {
        item["trainingId"]: item
        for item in db.workerTrainingProgress.find({"userId": user["_id"]})
    }
    shuttle_request = db.workerShuttleRequests.find_one(
        {
            "userId": user["_id"],
            "status": {"$ne": "replaced"},
        },
        sort=[("updatedAt", -1)],
    )

    return {
        "employerKey": employer_key,
        "assessments": [
            _merge_assessment_progress(item, assessment_results.get(item.get("id")))
            for item in assessment_catalog
            if item.get("id") in assigned_assessment_ids
        ],
        "trainings": [
            _merge_training_progress(item, training_progress.get(item.get("id")))
            for item in training_catalog
            if item.get("id") in assigned_training_ids
        ],
        "usefulInfo": config.get("usefulInfo", []),
        "shuttle": _merge_shuttle_request(config.get("shuttle", {"enabled": False, "routes": []}), shuttle_request),
    }


def answer_worker_question(db, user: dict, question: str) -> dict:
    config = get_or_create_worker_support_config(db, user.get("employerKey"))
    normalized_question = question.casefold()
    matched_answer = None
    matched_keywords = []

    for item in config.get("qaKnowledgeBase", []):
        keywords = item.get("keywords", [])
        if any(keyword.casefold() in normalized_question for keyword in keywords):
            matched_answer = item.get("answer")
            matched_keywords = keywords
            break

    if matched_answer is None:
        matched_answer = (
            "Sorun işveren ekibine iletildi. Yanıt geldiğinde burada görebilirsin."
        )
        status = "pending"
    else:
        status = "auto_answered"

    now = datetime.now(UTC)
    doc = {
        "userId": user["_id"],
        "employerKey": user.get("employerKey") or DEFAULT_EMPLOYER_KEY,
        "question": question,
        "answer": matched_answer,
        "status": status,
        "matchedKeywords": matched_keywords,
        "createdAt": now,
        "updatedAt": now,
    }
    result = db.workerQuestions.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def complete_assessment(db, user: dict, assessment_id: str, payload: dict | None = None) -> dict | None:
    payload = payload or {}
    assessment = _find_assigned_support_item(
        db,
        user,
        resource="assessments",
        item_id=assessment_id,
    )
    if assessment is None:
        return None

    now = datetime.now(UTC)
    answers = _normalize_assessment_answers(payload.get("answers", []))
    questions = assessment.get("questions", [])
    _validate_assessment_answers(questions, answers)
    score = _calculate_assessment_score(questions, answers)
    pass_score = assessment.get("passScore")
    passed = score >= pass_score if pass_score is not None else True
    attempt = {
        "score": score,
        "passScore": pass_score,
        "passed": passed,
        "answers": answers,
        "completedAt": now,
    }
    doc = {
        "userId": user["_id"],
        "employerKey": user.get("employerKey") or DEFAULT_EMPLOYER_KEY,
        "assessmentId": assessment_id,
        "title": assessment.get("title"),
        "status": "completed",
        "score": score,
        "passScore": pass_score,
        "passed": passed,
        "answers": answers,
        "completedAt": now,
        "updatedAt": now,
    }
    db.workerAssessmentResults.update_one(
        {"userId": user["_id"], "assessmentId": assessment_id},
        {
            "$set": doc,
            "$inc": {"attemptCount": 1},
            "$push": {
                "attemptHistory": {
                    "$each": [attempt],
                    "$slice": -20,
                }
            },
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    return db.workerAssessmentResults.find_one({"userId": user["_id"], "assessmentId": assessment_id})


def complete_training(db, user: dict, training_id: str, payload: dict | None = None) -> dict | None:
    payload = payload or {}
    training = _find_assigned_support_item(
        db,
        user,
        resource="trainings",
        item_id=training_id,
    )
    if training is None:
        return None

    module_ids = [
        module.get("id")
        for module in training.get("modules", [])
        if module.get("id")
    ]
    completed_modules = _validate_training_completion(
        module_ids,
        payload.get("completedModules"),
    )
    return _upsert_training_progress(
        db,
        user,
        training,
        completed_modules,
    )


def save_training_progress(
    db,
    user: dict,
    training_id: str,
    payload: dict | None = None,
) -> dict | None:
    payload = payload or {}
    training = _find_assigned_support_item(
        db,
        user,
        resource="trainings",
        item_id=training_id,
    )
    if training is None:
        return None

    module_ids = [
        module.get("id")
        for module in training.get("modules", [])
        if module.get("id")
    ]
    completed_modules = _validate_training_progress(
        module_ids,
        payload.get("completedModules"),
    )
    existing = db.workerTrainingProgress.find_one(
        {
            "userId": user["_id"],
            "trainingId": training_id,
        }
    )
    if (
        existing is not None
        and existing.get("status") == "completed"
    ):
        if set(completed_modules) != set(module_ids):
            raise Conflict(
                "Completed training progress cannot be reduced"
            )
        return existing

    return _upsert_training_progress(
        db,
        user,
        training,
        completed_modules,
    )


def _upsert_training_progress(
    db,
    user: dict,
    training: dict,
    completed_modules: list[str],
) -> dict:
    training_id = training["id"]
    module_ids = [
        module.get("id")
        for module in training.get("modules", [])
        if module.get("id")
    ]
    is_completed = bool(module_ids) and len(completed_modules) == len(
        module_ids
    )
    progress_percent = (
        round((len(completed_modules) / len(module_ids)) * 100)
        if module_ids
        else 0
    )
    now = datetime.now(UTC)
    doc = {
        "userId": user["_id"],
        "employerKey": user.get("employerKey") or DEFAULT_EMPLOYER_KEY,
        "trainingId": training_id,
        "title": training.get("title"),
        "status": "completed" if is_completed else "in_progress",
        "progressPercent": progress_percent,
        "completedModules": completed_modules,
        "completedAt": now if is_completed else None,
        "updatedAt": now,
    }
    db.workerTrainingProgress.update_one(
        {"userId": user["_id"], "trainingId": training_id},
        {"$set": doc, "$setOnInsert": {"createdAt": now}},
        upsert=True,
    )
    return db.workerTrainingProgress.find_one({"userId": user["_id"], "trainingId": training_id})


def request_shuttle(db, user: dict, route_id: str, pickup_note: str | None = None) -> dict | None:
    config = get_or_create_worker_support_config(db, user.get("employerKey"))
    shuttle = config.get("shuttle", {})
    if not shuttle.get("enabled"):
        return None

    route = _find_item(shuttle.get("routes", []), route_id)
    if route is None:
        return None

    now = datetime.now(UTC)
    db.workerShuttleRequests.update_many(
        {
            "userId": user["_id"],
            "status": {"$in": ["requested", "confirmed"]},
        },
        {"$set": {"status": "replaced", "updatedAt": now}},
    )
    doc = {
        "userId": user["_id"],
        "employerKey": user.get("employerKey") or DEFAULT_EMPLOYER_KEY,
        "routeId": route_id,
        "routeName": route.get("name"),
        "pickupWindow": route.get("pickupWindow"),
        "pickupNote": pickup_note or "",
        "status": "requested",
        "createdAt": now,
        "updatedAt": now,
    }
    result = db.workerShuttleRequests.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def cancel_shuttle_request(
    db,
    user: dict,
    request_id: str,
) -> dict | None:
    if not ObjectId.is_valid(request_id):
        return None

    query = {
        "_id": ObjectId(request_id),
        "userId": user["_id"],
    }
    shuttle_request = db.workerShuttleRequests.find_one(query)
    if shuttle_request is None:
        return None
    if shuttle_request.get("status") == "cancelled":
        return shuttle_request
    if shuttle_request.get("status") not in {
        "requested",
        "confirmed",
    }:
        raise Conflict("Shuttle request cannot be cancelled")

    now = datetime.now(UTC)
    result = db.workerShuttleRequests.update_one(
        {
            **query,
            "status": shuttle_request["status"],
        },
        {
            "$set": {
                "status": "cancelled",
                "cancelledAt": now,
                "updatedAt": now,
            }
        },
    )
    if result.modified_count != 1:
        raise Conflict("Shuttle request changed concurrently")
    return db.workerShuttleRequests.find_one(query)


def _find_item(items: list[dict], item_id: str) -> dict | None:
    return next((item for item in items if item.get("id") == item_id), None)


def _available_items(items: list[dict]) -> list[dict]:
    return [
        item
        for item in items
        if item.get("status", "available") == "available"
    ]


def _selected_assignment_ids(
    assignment: dict | None,
    field: str,
    catalog: list[dict],
) -> list[str]:
    catalog_ids = [
        item["id"]
        for item in catalog
        if item.get("id")
    ]
    if assignment is None:
        return catalog_ids
    selected_ids = set(assignment.get(field, []))
    return [
        item_id
        for item_id in catalog_ids
        if item_id in selected_ids
    ]


def _normalize_assignment_ids(
    raw_ids,
    field: str,
    catalog: list[dict],
) -> list[str]:
    if not isinstance(raw_ids, list):
        raise BadRequest(f"{field} must be an array")
    if len(raw_ids) > 100:
        raise BadRequest(f"{field} cannot contain more than 100 items")
    if any(
        not isinstance(item_id, str) or not item_id.strip()
        for item_id in raw_ids
    ):
        raise BadRequest(f"{field} must contain non-empty strings")

    normalized_ids = [item_id.strip() for item_id in raw_ids]
    if len(normalized_ids) != len(set(normalized_ids)):
        raise BadRequest(f"{field} cannot contain duplicate ids")

    catalog_ids = {
        item["id"]
        for item in catalog
        if item.get("id")
    }
    invalid_ids = [
        item_id
        for item_id in normalized_ids
        if item_id not in catalog_ids
    ]
    if invalid_ids:
        raise BadRequest(
            f"{field} contains unknown or unavailable ids: "
            + ", ".join(sorted(invalid_ids))
        )
    selected_ids = set(normalized_ids)
    return [
        item["id"]
        for item in catalog
        if item.get("id") in selected_ids
    ]


def _assignment_catalog_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "description": item.get("description"),
        "durationMinutes": item.get("durationMinutes"),
        "required": item.get("required", False),
    }


def _find_assigned_support_item(
    db,
    user: dict,
    resource: str,
    item_id: str,
) -> dict | None:
    employer_key = user.get("employerKey") or DEFAULT_EMPLOYER_KEY
    config = get_or_create_worker_support_config(db, employer_key)
    catalog = _available_items(config.get(resource, []))
    assignment = db.workerSupportAssignments.find_one(
        {
            "userId": user["_id"],
            "employerKey": employer_key,
        }
    )
    field = (
        "assessmentIds"
        if resource == "assessments"
        else "trainingIds"
    )
    if item_id not in _selected_assignment_ids(
        assignment,
        field,
        catalog,
    ):
        return None
    return _find_item(catalog, item_id)


def _backfill_default_worker_support_config(db, config: dict) -> dict:
    updates = {}

    assessments = _merge_default_items(
        current_items=config.get("assessments", []),
        default_items=DEFAULT_WORKER_SUPPORT_CONFIG["assessments"],
        backfill_fields=["passScore", "questions"],
    )
    if assessments != config.get("assessments", []):
        updates["assessments"] = assessments

    trainings = _merge_default_items(
        current_items=config.get("trainings", []),
        default_items=DEFAULT_WORKER_SUPPORT_CONFIG["trainings"],
        backfill_fields=["modules"],
    )
    if trainings != config.get("trainings", []):
        updates["trainings"] = trainings

    if updates:
        updates["updatedAt"] = datetime.now(UTC)
        db.workerSupportConfigs.update_one({"_id": config["_id"]}, {"$set": updates})
        return db.workerSupportConfigs.find_one({"_id": config["_id"]})
    return config


def _backfill_worker_support_item_ids(db, config: dict) -> dict:
    updates = {}
    for field, prefix in (
        ("assessments", "assessment"),
        ("trainings", "training"),
        ("usefulInfo", "info"),
        ("qaKnowledgeBase", "qa"),
    ):
        items = _ensure_item_ids(config.get(field, []), prefix)
        if items != config.get(field, []):
            updates[field] = items

    shuttle = config.get("shuttle") or {}
    routes = _ensure_item_ids(shuttle.get("routes", []), "route")
    if routes != shuttle.get("routes", []):
        updates["shuttle.routes"] = routes

    if updates:
        updates["updatedAt"] = datetime.now(UTC)
        db.workerSupportConfigs.update_one(
            {"_id": config["_id"]}, {"$set": updates}
        )
        return db.workerSupportConfigs.find_one({"_id": config["_id"]})
    return config


def _ensure_item_ids(items: list[dict], prefix: str) -> list[dict]:
    used_ids = {
        item.get("id")
        for item in items
        if isinstance(item, dict) and item.get("id")
    }
    result = []
    next_index = 1
    for item in items:
        if not isinstance(item, dict) or item.get("id"):
            result.append(item)
            continue

        while f"{prefix}-{next_index}" in used_ids:
            next_index += 1
        item_id = f"{prefix}-{next_index}"
        used_ids.add(item_id)
        next_index += 1
        result.append({**item, "id": item_id})
    return result


def _merge_default_items(current_items: list[dict], default_items: list[dict], backfill_fields: list[str]) -> list[dict]:
    current_by_id = {item.get("id"): item for item in current_items if item.get("id")}
    merged_items = []

    for default_item in default_items:
        item_id = default_item.get("id")
        current_item = current_by_id.get(item_id)
        if current_item is None:
            merged_items.append(default_item)
            continue

        merged_item = {**current_item}
        for field in backfill_fields:
            if not merged_item.get(field) and default_item.get(field):
                merged_item[field] = default_item[field]
        merged_items.append(merged_item)

    default_ids = {item.get("id") for item in default_items}
    merged_items.extend(item for item in current_items if item.get("id") not in default_ids)
    return merged_items


def _merge_assessment_progress(assessment: dict, result: dict | None) -> dict:
    if result is None:
        return assessment
    return {
        **assessment,
        "status": result.get("status", assessment.get("status")),
        "score": result.get("score"),
        "passScore": result.get("passScore", assessment.get("passScore")),
        "passed": result.get("passed"),
        "answers": result.get("answers", []),
        "attemptCount": result.get("attemptCount", 1),
        "completedAt": result.get("completedAt"),
    }


def _merge_training_progress(training: dict, progress: dict | None) -> dict:
    if progress is None:
        return training
    return {
        **training,
        "status": progress.get("status", training.get("status")),
        "progressPercent": progress.get("progressPercent"),
        "completedModules": progress.get("completedModules", []),
        "completedAt": progress.get("completedAt"),
    }


def _merge_shuttle_request(shuttle: dict, request: dict | None) -> dict:
    if request is None:
        return shuttle
    return {
        **shuttle,
        "requestId": str(request["_id"]),
        "selectedRouteId": request.get("routeId"),
        "selectedRouteName": request.get("routeName"),
        "requestStatus": request.get("status"),
        "pickupNote": request.get("pickupNote"),
        "decisionNote": request.get("decisionNote"),
        "requestedAt": request.get("createdAt"),
    }


def _normalize_assessment_answers(raw_answers) -> list[dict]:
    if not isinstance(raw_answers, list):
        return []

    answers = []
    for item in raw_answers:
        if not isinstance(item, dict):
            continue
        question_id = item.get("questionId")
        option_id = item.get("optionId")
        if question_id and option_id:
            answers.append({"questionId": question_id, "optionId": option_id})
    return answers


def _validate_assessment_answers(
    questions: list[dict], answers: list[dict]
) -> None:
    if not questions:
        raise BadRequest("Assessment has no questions")

    answer_by_question = {}
    for answer in answers:
        question_id = answer["questionId"]
        if question_id in answer_by_question:
            raise BadRequest(f"Duplicate answer for question: {question_id}")
        answer_by_question[question_id] = answer["optionId"]

    question_ids = {question.get("id") for question in questions}
    if set(answer_by_question) != question_ids:
        raise BadRequest("All assessment questions must be answered")

    for question in questions:
        option_ids = {
            option.get("id") for option in question.get("options", [])
        }
        if answer_by_question[question.get("id")] not in option_ids:
            raise BadRequest(
                f"Invalid option for question: {question.get('id')}"
            )


def _validate_training_completion(
    module_ids: list[str], raw_completed_modules
) -> list[str]:
    if not module_ids:
        raise BadRequest("Training has no modules")
    if not isinstance(raw_completed_modules, list):
        raise BadRequest("completedModules must be a list")
    if not all(
        isinstance(module_id, str) and module_id
        for module_id in raw_completed_modules
    ):
        raise BadRequest(
            "completedModules must contain non-empty module ids"
        )
    if len(raw_completed_modules) != len(set(raw_completed_modules)):
        raise BadRequest("completedModules cannot contain duplicates")

    expected = set(module_ids)
    completed = set(raw_completed_modules)
    if completed != expected:
        raise BadRequest(
            "All training modules must be completed exactly once"
        )
    return module_ids


def _validate_training_progress(
    module_ids: list[str],
    raw_completed_modules,
) -> list[str]:
    if not module_ids:
        raise BadRequest("Training has no modules")
    if not isinstance(raw_completed_modules, list):
        raise BadRequest("completedModules must be a list")
    if not all(
        isinstance(module_id, str) and module_id
        for module_id in raw_completed_modules
    ):
        raise BadRequest(
            "completedModules must contain non-empty module ids"
        )
    if len(raw_completed_modules) != len(set(raw_completed_modules)):
        raise BadRequest("completedModules cannot contain duplicates")

    unknown_modules = set(raw_completed_modules) - set(module_ids)
    if unknown_modules:
        raise BadRequest(
            "completedModules contains unknown module ids"
        )
    completed = set(raw_completed_modules)
    return [
        module_id
        for module_id in module_ids
        if module_id in completed
    ]


def _calculate_assessment_score(questions: list[dict], answers: list[dict]) -> int:
    selected_options = {item["questionId"]: item["optionId"] for item in answers}
    total_score = 0
    max_score = 0

    for question in questions:
        options = question.get("options", [])
        if not options:
            continue

        option_scores = [int(option.get("score", 0)) for option in options]
        max_score += max(option_scores)

        selected_option_id = selected_options.get(question.get("id"))
        selected_option = _find_item(options, selected_option_id) if selected_option_id else None
        if selected_option is not None:
            total_score += int(selected_option.get("score", 0))

    if max_score <= 0:
        return 100
    return round((total_score / max_score) * 100)
