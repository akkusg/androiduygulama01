package com.example.m7_24

import com.example.m7_24.api.DashboardResponse

internal data class ApplicationNotificationState(
    val id: String,
    val status: String,
    val title: String,
    val interviewAt: String = "",
)

internal data class ShuttleNotificationState(
    val status: String,
    val routeName: String,
    val decisionNote: String,
)

internal data class DashboardNotificationSnapshot(
    val applications: Map<String, ApplicationNotificationState>,
    val shuttle: ShuttleNotificationState?,
    val answeredQuestions: Map<String, String>,
)

internal data class WorkerNotificationEvent(
    val key: String,
    val title: String,
    val body: String,
)

internal fun DashboardResponse.toNotificationSnapshot():
    DashboardNotificationSnapshot {
    val recommendationApplications = recommendedJobs.mapNotNull { job ->
        val id = job.applicationId?.takeIf { it.isNotBlank() }
            ?: return@mapNotNull null
        val status = job.applicationStatus
            ?.takeIf { it.isNotBlank() }
            ?: return@mapNotNull null
        id to ApplicationNotificationState(
            id = id,
            status = status,
            title = job.title.orEmpty(),
            interviewAt = "",
        )
    }
    val historicalApplications = jobApplications.mapNotNull {
            application ->
        val id = application.id?.takeIf { it.isNotBlank() }
            ?: return@mapNotNull null
        val status = application.status?.takeIf { it.isNotBlank() }
            ?: return@mapNotNull null
        id to ApplicationNotificationState(
            id = id,
            status = status,
            title = application.job.title.orEmpty(),
            interviewAt =
                application.interview?.scheduledAt.orEmpty(),
        )
    }
    val applications = (
        recommendationApplications + historicalApplications
    ).toMap()
    val shuttle = workerHub?.shuttle?.let { item ->
        val status = item.requestStatus?.takeIf { it.isNotBlank() }
            ?: return@let null
        ShuttleNotificationState(
            status = status,
            routeName = item.selectedRouteName.orEmpty(),
            decisionNote = item.decisionNote.orEmpty(),
        )
    }
    val answeredQuestions = recentQuestions.mapNotNull { question ->
        if (question.status != "answered") return@mapNotNull null
        val id = question.id?.takeIf { it.isNotBlank() }
            ?: return@mapNotNull null
        id to ""
    }.toMap()
    return DashboardNotificationSnapshot(
        applications = applications,
        shuttle = shuttle,
        answeredQuestions = answeredQuestions,
    )
}

internal fun dashboardNotificationEvents(
    previous: DashboardNotificationSnapshot?,
    current: DashboardNotificationSnapshot,
): List<WorkerNotificationEvent> {
    if (previous == null) return emptyList()

    val events = mutableListOf<WorkerNotificationEvent>()
    current.applications.values.forEach { application ->
        val previousStatus = previous.applications[application.id]?.status
        if (
            previousStatus != null &&
            previousStatus != application.status
        ) {
            val jobTitle = application.title.ifBlank { "İş başvurunuz" }
            events += WorkerNotificationEvent(
                key = "application-${application.id}",
                title = "Başvuru durumunuz güncellendi",
                body = "$jobTitle: ${applicationStatusLabel(application.status)}",
            )
        } else if (
            previousStatus != null &&
            previous.applications[application.id]?.interviewAt !=
            application.interviewAt
        ) {
            val jobTitle =
                application.title.ifBlank { "İş başvurunuz" }
            events += WorkerNotificationEvent(
                key = "application-interview-${application.id}",
                title = if (application.interviewAt.isBlank()) {
                    "Görüşme planınız kaldırıldı"
                } else {
                    "Görüşme planınız güncellendi"
                },
                body = if (application.interviewAt.isBlank()) {
                    "$jobTitle için planlanan görüşme kaldırıldı."
                } else {
                    "$jobTitle için tarih ve görüşme detaylarını uygulamada görebilirsiniz."
                },
            )
        }
    }

    current.shuttle?.let { shuttle ->
        if (
            previous.shuttle?.status != shuttle.status &&
            shuttle.status != "requested"
        ) {
            val route = shuttle.routeName.ifBlank { "Servis talebiniz" }
            val decision = shuttle.decisionNote.takeIf {
                it.isNotBlank()
            }?.let { " $it" }.orEmpty()
            events += WorkerNotificationEvent(
                key = "shuttle",
                title = "Servis durumunuz güncellendi",
                body = "$route: ${shuttleStatusLabel(shuttle.status)}.$decision",
            )
        }
    }

    current.answeredQuestions.forEach { (id, _) ->
        if (id !in previous.answeredQuestions) {
            events += WorkerNotificationEvent(
                key = "question-$id",
                title = "Sorunuz yanıtlandı",
                body = "İşveren yanıtını uygulamada görebilirsiniz.",
            )
        }
    }
    return events
}

private fun applicationStatusLabel(status: String): String = when (status) {
    "submitted" -> "Başvuru alındı"
    "reviewing" -> "İncelemede"
    "shortlisted" -> "Kısa listede"
    "offered" -> "İş teklifiniz hazır"
    "offer_declined" -> "Teklif reddedildi"
    "rejected" -> "Reddedildi"
    "hired" -> "İşe alındınız"
    "withdrawn" -> "Geri çekildi"
    else -> "Durum değişti"
}

private fun shuttleStatusLabel(status: String): String = when (status) {
    "confirmed" -> "Onaylandı"
    "rejected" -> "Reddedildi"
    "cancelled" -> "İptal edildi"
    "completed" -> "Tamamlandı"
    else -> "Durum değişti"
}
