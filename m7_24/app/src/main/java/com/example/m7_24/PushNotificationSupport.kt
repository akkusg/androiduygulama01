package com.example.m7_24

internal data class WorkerPushPayload(
    val eventId: String,
    val eventType: String,
    val title: String,
    val body: String,
    val entityId: String,
    val status: String,
    val routeName: String,
)

internal fun parseWorkerPushPayload(
    data: Map<String, String>,
): WorkerPushPayload? {
    val eventId = data.boundedValue("eventId", 256) ?: return null
    val eventType = data.boundedValue("eventType", 64) ?: return null
    val title = data.boundedValue("title", 160) ?: return null
    val body = data.boundedValue("body", 500) ?: return null
    val entityId = data.boundedValue("entityId", 128) ?: return null
    val status = data.boundedValue("status", 64) ?: return null
    val routeName = data["routeName"]
        ?.trim()
        ?.takeIf { it.length <= 160 }
        .orEmpty()

    val validStatus = when (eventType) {
        "application_status" -> status in setOf(
            "submitted",
            "reviewing",
            "shortlisted",
            "offered",
            "rejected",
            "hired",
        )
        "question_answered" -> status == "answered"
        "shuttle_status" -> status in setOf(
            "confirmed",
            "rejected",
        )
        else -> false
    }
    if (!validStatus) return null

    return WorkerPushPayload(
        eventId = eventId,
        eventType = eventType,
        title = title,
        body = body,
        entityId = entityId,
        status = status,
        routeName = routeName,
    )
}

private fun Map<String, String>.boundedValue(
    key: String,
    maximumLength: Int,
): String? = get(key)
    ?.trim()
    ?.takeIf { it.isNotEmpty() && it.length <= maximumLength }
