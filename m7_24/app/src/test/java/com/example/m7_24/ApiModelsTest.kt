package com.example.m7_24

import com.example.m7_24.api.DashboardResponse
import com.example.m7_24.api.JobApplicationDto
import com.example.m7_24.api.JobApplicationJobDto
import com.example.m7_24.api.JobDto
import com.example.m7_24.api.ShuttleDto
import com.example.m7_24.api.TrainingDto
import com.example.m7_24.api.UserDto
import com.example.m7_24.api.VideoDto
import com.example.m7_24.api.WorkerHubDto
import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.TimeZone

class ApiModelsTest {
    @Test
    fun mobileConfigContractParsesVersionPolicy() {
        val config = Gson().fromJson(
            """
            {
              "platform": "android",
              "minSupportedVersionCode": 4,
              "latestVersionCode": 6,
              "maintenanceMode": false,
              "maintenanceMessage": "Bakım",
              "updateMessage": "Güncelle",
              "updateUrl": "https://example.com/app",
              "privacyPolicyUrl": "https://example.com/privacy",
              "videoConsentVersion": "video-processing-v1"
            }
            """.trimIndent(),
            com.example.m7_24.api.MobileConfigResponse::class.java,
        )

        assertEquals(4, config.minSupportedVersionCode)
        assertEquals(6, config.latestVersionCode)
        assertEquals("https://example.com/app", config.updateUrl)
        assertEquals(
            "https://example.com/privacy",
            config.privacyPolicyUrl,
        )
        assertEquals(
            "video-processing-v1",
            config.videoConsentVersion,
        )
    }

    @Test
    fun otpChallengeParsesServerControlledResendCooldown() {
        val challenge = Gson().fromJson(
            """
            {
              "challengeId": "challenge-1",
              "phone": "+905551112233",
              "expiresIn": 300,
              "resendAfterSeconds": 60
            }
            """.trimIndent(),
            com.example.m7_24.api.OtpChallengeResponse::class.java,
        )

        assertEquals(60, challenge.resendAfterSeconds)
        assertEquals("Kodu Tekrar Gönder", resendButtonLabel(0))
        assertEquals(
            "Kodu Tekrar Gönder (7 sn)",
            resendButtonLabel(7),
        )
    }

    @Test
    fun dashboardContractParsesPostingApplicationAndWorkerHub() {
        val dashboard = Gson().fromJson(
            """
            {
              "user": {
                "id": "worker-1",
                "name": "Ayşe Demir",
                "nameStatus": "confirmed_by_worker",
                "profileReviewStatus": "confirmed",
                "phone": "+905551112233",
                "profileStatus": "profile_ready",
                "videoStatus": "completed"
              },
              "latestVideo": null,
              "latestTranscript": null,
              "candidateProfile": {
                "name": "Ayşe Demir",
                "nameSource": "worker_review",
                "skills": ["kaynak", "iş güvenliği"]
              },
              "recommendedJobs": [
                {
                  "id": "recommendation-1",
                  "jobPostingId": "posting-1",
                  "title": "Kaynak Operatörü",
                  "matchScore": 94,
                  "applicationId": "application-1",
                  "applicationStatus": "submitted"
                }
              ],
              "jobApplications": [
                {
                  "id": "application-1",
                  "status": "reviewing",
                  "job": {
                    "title": "Kaynak Operatörü",
                    "company": "ACME"
                  },
                  "statusHistory": [
                    {
                      "status": "reviewing",
                      "note": "Telefon görüşmesi planlanacak."
                    }
                  ],
                  "interview": {
                    "scheduledAt": "2026-08-01T07:30:00+00:00",
                    "type": "onsite",
                    "location": "ACME Kocaeli Fabrikası",
                    "note": "Kimliğinizi getirin.",
                    "response": {
                      "status": "confirmed",
                      "note": "",
                      "respondedAt": "2026-07-30T08:00:00+00:00"
                    }
                  }
                }
              ],
              "workerHub": {
                "employerKey": "acme",
                "assessments": [],
                "trainings": [],
                "usefulInfo": [],
                "shuttle": {"enabled": true, "routes": []}
              },
              "videoConsent": {
                "type": "video_processing",
                "version": "video-processing-v1",
                "status": "accepted",
                "policyUrl": "https://example.com/privacy",
                "acceptedAt": "2026-07-28T06:00:00Z"
              },
              "recentQuestions": [],
              "pendingQuestionCount": 2
            }
            """.trimIndent(),
            DashboardResponse::class.java,
        )

        assertEquals("posting-1", dashboard.recommendedJobs.single().jobPostingId)
        assertEquals(
            "submitted",
            dashboard.recommendedJobs.single().applicationStatus,
        )
        assertEquals(
            "reviewing",
            dashboard.jobApplications.single().status,
        )
        assertEquals(
            "Telefon görüşmesi planlanacak.",
            dashboard.jobApplications.single()
                .statusHistory.single().note,
        )
        assertEquals(
            "ACME Kocaeli Fabrikası",
            dashboard.jobApplications.single().interview?.location,
        )
        assertEquals(
            "confirmed",
            dashboard.jobApplications.single()
                .interview?.response?.status,
        )
        assertEquals(
            listOf("kaynak", "iş güvenliği"),
            dashboard.candidateProfile?.skills,
        )
        assertEquals(
            "confirmed",
            dashboard.user.profileReviewStatus,
        )
        assertEquals("Ayşe Demir", dashboard.candidateProfile?.name)
        assertEquals("acme", dashboard.workerHub?.employerKey)
        assertNotNull(dashboard.workerHub?.shuttle)
        assertTrue(dashboard.workerHub?.shuttle?.enabled == true)
        assertEquals(
            "accepted",
            dashboard.videoConsent?.status,
        )
        assertEquals(2, dashboard.pendingQuestionCount)
    }

    @Test
    fun interviewDateIsRenderedInDeviceTimezone() {
        val previous = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Europe/Istanbul"))
            assertEquals(
                "01.08.2026 10:30",
                formatInterviewDate(
                    "2026-08-01T07:30:00.000000+00:00"
                ),
            )
        } finally {
            TimeZone.setDefault(previous)
        }
    }

    @Test
    fun dashboardPollingContinuesForActiveWorkerFlows() {
        val user = UserDto(
            id = "worker-1",
            name = "Test Worker",
            nameStatus = "inferred",
            phone = "+905551112233",
            employerKey = "default",
            phoneVerifiedAt = null,
            profileStatus = "registered",
            videoStatus = "not_uploaded",
            latestVideoId = null,
            createdAt = null,
            updatedAt = null,
        )
        fun dashboard(
            videoStatus: String? = null,
            pendingQuestions: Int = 0,
            jobStatus: String? = null,
            applicationHistoryStatus: String? = null,
            shuttleStatus: String? = null,
            trainingStatus: String? = null,
        ) = DashboardResponse(
            user = user,
            latestVideo = videoStatus?.let {
                VideoDto(
                    id = "video-1",
                    userId = user.id,
                    originalFilename = "video.mp4",
                    contentType = "video/mp4",
                    status = it,
                    createdAt = null,
                    updatedAt = null,
                )
            },
            latestTranscript = null,
            candidateProfile = null,
            recommendedJobs = jobStatus?.let {
                listOf(JobDto(applicationStatus = it))
            }.orEmpty(),
            jobApplications = applicationHistoryStatus?.let {
                listOf(
                    JobApplicationDto(
                        id = "application-1",
                        status = it,
                        job = JobApplicationJobDto(
                            title = "Kaynak Operatörü",
                        ),
                    )
                )
            }.orEmpty(),
            workerHub = if (
                shuttleStatus != null || trainingStatus != null
            ) {
                WorkerHubDto(
                    shuttle = shuttleStatus?.let {
                        ShuttleDto(requestStatus = it)
                    },
                    trainings = trainingStatus?.let {
                        listOf(TrainingDto(status = it))
                    }.orEmpty(),
                )
            } else {
                null
            },
            pendingQuestionCount = pendingQuestions,
        )

        assertEquals(2_000L, dashboardRefreshDelay(dashboard("processing")))
        assertEquals(15_000L, dashboardRefreshDelay(dashboard(pendingQuestions = 1)))
        assertEquals(
            60_000L,
            dashboardRefreshDelay(dashboard(jobStatus = "submitted")),
        )
        assertEquals(
            60_000L,
            dashboardRefreshDelay(dashboard(jobStatus = "reviewing")),
        )
        assertEquals(
            60_000L,
            dashboardRefreshDelay(dashboard(jobStatus = "shortlisted")),
        )
        assertEquals(
            60_000L,
            dashboardRefreshDelay(
                dashboard(
                    applicationHistoryStatus = "reviewing",
                )
            ),
        )
        assertEquals(
            60_000L,
            dashboardRefreshDelay(
                dashboard(trainingStatus = "in_progress")
            ),
        )
        assertEquals(
            60_000L,
            dashboardRefreshDelay(dashboard(shuttleStatus = "requested")),
        )
        assertEquals(
            null,
            dashboardRefreshDelay(dashboard(jobStatus = "hired")),
        )
        assertEquals(
            null,
            dashboardRefreshDelay(dashboard(shuttleStatus = "confirmed")),
        )
        assertEquals(null, dashboardRefreshDelay(dashboard()))
    }
}
