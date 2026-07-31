package com.example.m7_24

import com.example.m7_24.api.DashboardResponse
import com.example.m7_24.api.JobApplicationDto
import com.example.m7_24.api.JobApplicationJobDto
import com.example.m7_24.api.UserDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkerNotificationSupportTest {
    @Test
    fun applicationHistoryRemainsInSnapshotWithoutRecommendation() {
        val dashboard = DashboardResponse(
            user = UserDto(
                id = "worker-1",
                name = "Test Kullanıcı",
                nameStatus = "confirmed_by_worker",
                phone = "+905551112233",
                employerKey = "default",
                phoneVerifiedAt = null,
                profileStatus = "profile_ready",
                videoStatus = "completed",
                latestVideoId = null,
                createdAt = null,
                updatedAt = null,
            ),
            latestVideo = null,
            latestTranscript = null,
            candidateProfile = null,
            recommendedJobs = emptyList(),
            jobApplications = listOf(
                JobApplicationDto(
                    id = "application-1",
                    status = "shortlisted",
                    job = JobApplicationJobDto(
                        title = "Kaynak Operatörü",
                    ),
                )
            ),
            workerHub = null,
        )

        val application = dashboard.toNotificationSnapshot()
            .applications["application-1"]

        assertEquals("shortlisted", application?.status)
        assertEquals("Kaynak Operatörü", application?.title)
    }

    @Test
    fun firstSnapshotOnlyEstablishesBaseline() {
        val current = snapshot(
            applicationStatus = "reviewing",
            shuttleStatus = "requested",
            answeredQuestionIds = setOf("question-1"),
        )

        assertTrue(
            dashboardNotificationEvents(null, current).isEmpty()
        )
    }

    @Test
    fun applicationStatusChangeCreatesTurkishNotification() {
        val previous = snapshot(applicationStatus = "reviewing")
        val current = snapshot(applicationStatus = "shortlisted")

        val events = dashboardNotificationEvents(previous, current)

        assertEquals(1, events.size)
        assertEquals(
            "Başvuru durumunuz güncellendi",
            events.single().title,
        )
        assertEquals(
            "Kaynak Operatörü: Kısa listede",
            events.single().body,
        )
    }

    @Test
    fun jobOfferStatusCreatesOfferNotification() {
        val previous = snapshot(applicationStatus = "shortlisted")
        val current = snapshot(applicationStatus = "offered")

        val events = dashboardNotificationEvents(previous, current)

        assertEquals(1, events.size)
        assertEquals(
            "Kaynak Operatörü: İş teklifiniz hazır",
            events.single().body,
        )
    }

    @Test
    fun interviewScheduleChangeCreatesNotification() {
        val previous = snapshot(
            applicationStatus = "shortlisted",
        )
        val current = snapshot(
            applicationStatus = "shortlisted",
            interviewAt = "2026-08-01T07:30:00+00:00",
        )

        val events = dashboardNotificationEvents(previous, current)

        assertEquals(1, events.size)
        assertEquals(
            "Görüşme planınız güncellendi",
            events.single().title,
        )
        assertEquals(
            "Kaynak Operatörü için tarih ve görüşme " +
                "detaylarını uygulamada görebilirsiniz.",
            events.single().body,
        )
    }

    @Test
    fun shuttleDecisionAndNewHumanAnswerCreateSeparateNotifications() {
        val previous = snapshot(
            applicationStatus = "reviewing",
            shuttleStatus = "requested",
        )
        val current = snapshot(
            applicationStatus = "reviewing",
            shuttleStatus = "confirmed",
            answeredQuestionIds = setOf("question-2"),
        )

        val events = dashboardNotificationEvents(previous, current)

        assertEquals(2, events.size)
        assertEquals(
            setOf(
                "Servis durumunuz güncellendi",
                "Sorunuz yanıtlandı",
            ),
            events.map { it.title }.toSet(),
        )
        assertEquals(
            "İşveren yanıtını uygulamada görebilirsiniz.",
            events.single { it.title == "Sorunuz yanıtlandı" }.body,
        )
    }

    @Test
    fun unchangedSnapshotDoesNotNotify() {
        val snapshot = snapshot(
            applicationStatus = "reviewing",
            shuttleStatus = "confirmed",
            answeredQuestionIds = setOf("question-1"),
        )

        assertTrue(
            dashboardNotificationEvents(snapshot, snapshot).isEmpty()
        )
    }

    @Test
    fun validFidPushPayloadIsParsed() {
        val payload = parseWorkerPushPayload(
            mapOf(
                "eventId" to "application:123:event-1",
                "eventType" to "application_status",
                "title" to "Başvuru durumunuz güncellendi",
                "body" to "Kaynak Operatörü: Kısa listede",
                "entityId" to "application-1",
                "status" to "shortlisted",
            )
        )

        assertEquals(
            WorkerPushPayload(
                eventId = "application:123:event-1",
                eventType = "application_status",
                title = "Başvuru durumunuz güncellendi",
                body = "Kaynak Operatörü: Kısa listede",
                entityId = "application-1",
                status = "shortlisted",
                routeName = "",
            ),
            payload,
        )
        assertEquals(
            "offered",
            parseWorkerPushPayload(
                mapOf(
                    "eventId" to "application:123:event-2",
                    "eventType" to "application_status",
                    "title" to "İş teklifiniz hazır",
                    "body" to "Teklif detaylarını uygulamada görün.",
                    "entityId" to "application-1",
                    "status" to "offered",
                )
            )?.status,
        )
    }

    @Test
    fun malformedOrUnsupportedPushPayloadIsRejected() {
        val base = mapOf(
            "eventId" to "event-1",
            "eventType" to "shuttle_status",
            "title" to "Servis güncellendi",
            "body" to "Merkez hattı: Onaylandı",
            "entityId" to "shuttle-1",
            "status" to "confirmed",
        )

        assertEquals(
            null,
            parseWorkerPushPayload(base - "eventId"),
        )
        assertEquals(
            null,
            parseWorkerPushPayload(
                base + ("status" to "requested")
            ),
        )
        assertEquals(
            null,
            parseWorkerPushPayload(
                base + ("eventType" to "unknown")
            ),
        )
        assertEquals(
            null,
            parseWorkerPushPayload(
                base + ("body" to "x".repeat(501))
            ),
        )
    }

    private fun snapshot(
        applicationStatus: String? = null,
        interviewAt: String = "",
        shuttleStatus: String? = null,
        answeredQuestionIds: Set<String> = emptySet(),
    ): DashboardNotificationSnapshot {
        val applications = applicationStatus?.let {
            mapOf(
                "application-1" to ApplicationNotificationState(
                    id = "application-1",
                    status = it,
                    title = "Kaynak Operatörü",
                    interviewAt = interviewAt,
                )
            )
        }.orEmpty()
        val shuttle = shuttleStatus?.let {
            ShuttleNotificationState(
                status = it,
                routeName = "Merkez Hattı",
                decisionNote = "",
            )
        }
        return DashboardNotificationSnapshot(
            applications = applications,
            shuttle = shuttle,
            answeredQuestions = answeredQuestionIds.associateWith {
                "Servis saatim nedir?"
            },
        )
    }
}
