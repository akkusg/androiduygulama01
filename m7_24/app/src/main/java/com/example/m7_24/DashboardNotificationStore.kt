package com.example.m7_24

import android.content.Context
import android.util.Base64

internal class DashboardNotificationStore(context: Context) {
    private val preferences = context.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )

    fun load(): DashboardNotificationSnapshot? {
        if (!preferences.getBoolean(KEY_INITIALIZED, false)) return null

        val applications = preferences.getStringSet(
            KEY_APPLICATIONS,
            emptySet(),
        ).orEmpty().mapNotNull(::decodeApplication).associateBy { it.id }
        val answeredQuestions = preferences.getStringSet(
            KEY_ANSWERED_QUESTIONS,
            emptySet(),
        ).orEmpty().associateWith { "" }
        val shuttleStatus = preferences.getString(
            KEY_SHUTTLE_STATUS,
            null,
        )
        val shuttle = shuttleStatus?.let {
            ShuttleNotificationState(
                status = it,
                routeName = preferences.getString(
                    KEY_SHUTTLE_ROUTE,
                    "",
                ).orEmpty(),
                decisionNote = preferences.getString(
                    KEY_SHUTTLE_NOTE,
                    "",
                ).orEmpty(),
            )
        }
        return DashboardNotificationSnapshot(
            applications = applications,
            shuttle = shuttle,
            answeredQuestions = answeredQuestions,
        )
    }

    fun save(snapshot: DashboardNotificationSnapshot) {
        preferences.edit()
            .putBoolean(KEY_INITIALIZED, true)
            .putStringSet(
                KEY_APPLICATIONS,
                snapshot.applications.values
                    .map(::encodeApplication)
                    .toSet(),
            )
            .putStringSet(
                KEY_ANSWERED_QUESTIONS,
                snapshot.answeredQuestions.keys,
            )
            .putString(
                KEY_SHUTTLE_STATUS,
                snapshot.shuttle?.status,
            )
            .putString(
                KEY_SHUTTLE_ROUTE,
                snapshot.shuttle?.routeName,
            )
            .putString(
                KEY_SHUTTLE_NOTE,
                snapshot.shuttle?.decisionNote,
            )
            .commit()
    }

    fun clear() {
        preferences.edit().clear().commit()
    }

    fun applyPushEvent(payload: WorkerPushPayload) {
        val current = load() ?: DashboardNotificationSnapshot(
            applications = emptyMap(),
            shuttle = null,
            answeredQuestions = emptyMap(),
        )
        val updated = when (payload.eventType) {
            "application_status" -> current.copy(
                applications = current.applications + (
                    payload.entityId to ApplicationNotificationState(
                        id = payload.entityId,
                        status = payload.status,
                        title = current.applications[
                            payload.entityId
                        ]?.title.orEmpty(),
                        interviewAt = current.applications[
                            payload.entityId
                        ]?.interviewAt.orEmpty(),
                    )
                )
            )
            "question_answered" -> current.copy(
                answeredQuestions =
                    current.answeredQuestions + (payload.entityId to "")
            )
            "shuttle_status" -> current.copy(
                shuttle = ShuttleNotificationState(
                    status = payload.status,
                    routeName = payload.routeName.ifBlank {
                        current.shuttle?.routeName.orEmpty()
                    },
                    decisionNote =
                        current.shuttle?.decisionNote.orEmpty(),
                )
            )
            else -> return
        }
        save(updated)
    }

    private fun encodeApplication(
        application: ApplicationNotificationState,
    ): String {
        val encodedTitle = Base64.encodeToString(
            application.title.toByteArray(Charsets.UTF_8),
            Base64.NO_WRAP,
        )
        return listOf(
            application.id,
            application.status,
            encodedTitle,
            application.interviewAt,
        ).joinToString(SEPARATOR)
    }

    private fun decodeApplication(
        encoded: String,
    ): ApplicationNotificationState? {
        val parts = encoded.split(SEPARATOR, limit = 4)
        if (
            parts.size !in 3..4 ||
            parts[0].isBlank() ||
            parts[1].isBlank()
        ) {
            return null
        }
        val title = runCatching {
            Base64.decode(parts[2], Base64.NO_WRAP)
                .toString(Charsets.UTF_8)
        }.getOrDefault("")
        return ApplicationNotificationState(
            id = parts[0],
            status = parts[1],
            title = title,
            interviewAt = parts.getOrElse(3) { "" },
        )
    }

    private companion object {
        const val PREFERENCES_NAME = "m7_24_dashboard_notifications"
        const val KEY_INITIALIZED = "initialized"
        const val KEY_APPLICATIONS = "applications"
        const val KEY_ANSWERED_QUESTIONS = "answered_questions"
        const val KEY_SHUTTLE_STATUS = "shuttle_status"
        const val KEY_SHUTTLE_ROUTE = "shuttle_route"
        const val KEY_SHUTTLE_NOTE = "shuttle_note"
        const val SEPARATOR = "|"
    }
}
