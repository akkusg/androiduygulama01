package com.example.m7_24

import android.content.Context
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.example.m7_24.api.JobDto
import com.example.m7_24.api.AssessmentDto
import com.example.m7_24.api.AssessmentOptionDto
import com.example.m7_24.api.AssessmentQuestionDto
import com.example.m7_24.api.CandidateProfileDto
import com.example.m7_24.api.JobApplicationDto
import com.example.m7_24.api.JobApplicationInterviewDto
import com.example.m7_24.api.JobApplicationJobDto
import com.example.m7_24.api.JobApplicationStatusHistoryDto
import com.example.m7_24.api.ShuttleDto
import com.example.m7_24.api.ShuttleRouteDto
import com.example.m7_24.api.TrainingDto
import com.example.m7_24.api.TrainingModuleDto
import com.example.m7_24.api.UserDto
import com.example.m7_24.api.WorkerHubDto
import com.example.m7_24.ui.theme.M7_24Theme
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AppInstrumentedTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun updateGateShowsRequiredActionAndSupportsRetry() {
        var updates = 0
        var retries = 0
        composeRule.setContent {
            M7_24Theme {
                AppAvailabilityScreen(
                    title = "Güncelleme gerekli",
                    message = "Yeni sürümü yükleyin.",
                    updateUrl = "https://example.com/app",
                    onUpdate = { updates += 1 },
                    onRetry = { retries += 1 },
                )
            }
        }

        composeRule.onNodeWithText("Güncelleme gerekli")
            .assertIsDisplayed()
        composeRule.onNodeWithTag("mobile_gate_update")
            .performClick()
        composeRule.onNodeWithTag("mobile_gate_retry")
            .performClick()
        composeRule.runOnIdle {
            assertEquals(1, updates)
            assertEquals(1, retries)
        }
    }

    @Test
    fun registrationCollectsOnlyPhoneAndValidatesEmptySubmission() {
        composeRule.setContent {
            M7_24Theme {
                RegistrationScreen(onRegisterSuccess = { _, _ -> })
            }
        }

        composeRule.onNodeWithText("Telefonunuzu Doğrulayın")
            .assertIsDisplayed()
        composeRule.onNodeWithTag("phone_input")
            .assertIsDisplayed()
        composeRule.onNodeWithText("Ad Soyad")
            .assertDoesNotExist()
        composeRule.onNodeWithTag("registration_submit")
            .assertTextContains("Kod Gönder")
            .performClick()
        composeRule.onNodeWithText("Telefon numarası zorunludur.")
            .assertIsDisplayed()
    }

    @Test
    fun registrationRejectsMalformedPhoneBeforeSubmitting() {
        composeRule.setContent {
            M7_24Theme {
                RegistrationScreen(onRegisterSuccess = { _, _ -> })
            }
        }

        composeRule.onNodeWithTag("phone_input")
            .performTextInput("+0955")
        composeRule.onNodeWithTag("registration_submit")
            .performClick()
        composeRule.onNodeWithText("Geçerli bir telefon numarası girin.")
            .assertIsDisplayed()
    }

    @Test
    fun videoConsentRequiresExplicitSelectionBeforeContinuing() {
        val checked = mutableStateOf(false)
        var acceptRequests = 0
        var privacyRequests = 0
        composeRule.setContent {
            M7_24Theme {
                VideoConsentScreen(
                    checked = checked.value,
                    isSubmitting = false,
                    errorMessage = null,
                    privacyPolicyUrl = "https://example.com/privacy",
                    onCheckedChange = { checked.value = it },
                    onOpenPrivacy = { privacyRequests += 1 },
                    onAccept = { acceptRequests += 1 },
                )
            }
        }

        composeRule.onNodeWithText("Video İşleme Onayı")
            .assertIsDisplayed()
        composeRule.onNodeWithTag("video_consent_accept")
            .assertIsNotEnabled()
        composeRule.onNodeWithTag("video_consent_privacy")
            .performClick()
        composeRule.onNodeWithTag("video_consent_checkbox")
            .performClick()
        composeRule.onNodeWithTag("video_consent_accept")
            .assertIsEnabled()
            .performClick()
        composeRule.runOnIdle {
            assertEquals(1, privacyRequests)
            assertEquals(1, acceptRequests)
        }
    }

    @Test
    fun jobApplicationButtonReflectsApplicationState() {
        var applyClicks = 0
        val jobState = mutableStateOf(
            JobDto(
                id = "recommendation-1",
                title = "Kaynak Operatörü",
                company = "Yedi Yirmi Dört",
                location = "Kocaeli",
                matchScore = 94,
                applicationStatus = "not_applied",
            )
        )
        composeRule.setContent {
            M7_24Theme {
                JobRecommendationCard(
                    job = jobState.value,
                    isApplying = false,
                    onApply = { applyClicks += 1 },
                )
            }
        }

        composeRule.onNodeWithTag(
            "job_apply_button_recommendation-1"
        )
            .assertIsEnabled()
            .performClick()
        composeRule.runOnIdle {
            assertEquals(1, applyClicks)
            jobState.value = jobState.value.copy(
                applicationStatus = "submitted"
            )
        }

        composeRule.onNodeWithTag(
            "job_apply_button_recommendation-1"
        )
            .assertIsNotEnabled()
        composeRule.onNodeWithText("Başvuru durumu: Başvuru alındı")
            .assertIsDisplayed()
    }

    @Test
    fun accountDeletionRequiresExplicitSecondConfirmation() {
        var confirmations = 0
        var exportRequests = 0
        composeRule.setContent {
            M7_24Theme {
                AccountDeletionSection(
                    isDeleting = false,
                    isExporting = false,
                    errorMessage = null,
                    onExport = { exportRequests += 1 },
                    onConfirm = { confirmations += 1 },
                )
            }
        }

        composeRule.onNodeWithTag("account_data_export")
            .performClick()
        composeRule.runOnIdle {
            assertEquals(1, exportRequests)
        }
        composeRule.onNodeWithTag("account_delete_open")
            .performClick()
        composeRule.onNodeWithText("Hesabı kalıcı olarak sil")
            .assertIsDisplayed()
        composeRule.runOnIdle {
            assertEquals(0, confirmations)
        }
        composeRule.onNodeWithTag("account_delete_confirm")
            .performClick()
        composeRule.runOnIdle {
            assertEquals(1, confirmations)
        }
    }

    @Test
    fun videoConsentWithdrawalRequiresConfirmation() {
        var withdrawals = 0
        composeRule.setContent {
            M7_24Theme {
                VideoConsentManagementSection(
                    consentStatus = "accepted",
                    isWithdrawing = false,
                    successMessage = null,
                    errorMessage = null,
                    onWithdraw = { withdrawals += 1 },
                )
            }
        }

        composeRule.onNodeWithTag("video_consent_withdraw_open")
            .performClick()
        composeRule.onNodeWithText(
            "Video işleme onayını geri çek"
        ).assertIsDisplayed()
        composeRule.runOnIdle {
            assertEquals(0, withdrawals)
        }
        composeRule.onNodeWithTag(
            "video_consent_withdraw_confirm"
        ).performClick()
        composeRule.runOnIdle {
            assertEquals(1, withdrawals)
        }
    }

    @Test
    fun notificationPermissionActionRequestsPermission() {
        var requests = 0
        composeRule.setContent {
            M7_24Theme {
                NotificationPermissionAction(
                    onRequest = { requests += 1 }
                )
            }
        }

        composeRule.onNodeWithText("İşveren güncellemeleri")
            .assertIsDisplayed()
        composeRule.onNodeWithTag("enable_notifications")
            .assertIsDisplayed()
            .performClick()
        composeRule.runOnIdle {
            assertEquals(1, requests)
        }
    }

    @Test
    fun inferredProfileNameCanBeCorrectedAndSaved() {
        val name = mutableStateOf("Mehmet Yılmaz")
        var savedName = ""
        composeRule.setContent {
            M7_24Theme {
                ProfileReviewCard(
                    user = profileUser(
                        name = "Mehmet Yılmaz",
                        reviewStatus = "pending",
                    ),
                    profile = CandidateProfileDto(
                        name = "Mehmet Yılmaz",
                        summary = "Kaynak deneyimi bulunuyor.",
                        skills = listOf("kaynak"),
                    ),
                    nameInput = name.value,
                    isEditing = true,
                    isSaving = false,
                    successMessage = null,
                    errorMessage = null,
                    onNameChange = { name.value = it },
                    onEdit = {},
                    onCancel = {},
                    onSave = { savedName = name.value },
                )
            }
        }

        composeRule.onNodeWithText("Ad onayı bekliyor")
            .assertIsDisplayed()
        composeRule.onNodeWithTag("profile_name_input")
            .performTextReplacement("Mehmet Yalçın")
        composeRule.onNodeWithTag("profile_name_save")
            .assertIsEnabled()
            .performClick()
        composeRule.runOnIdle {
            assertEquals("Mehmet Yalçın", savedName)
        }
    }

    @Test
    fun confirmedProfileNameShowsEditAction() {
        var edits = 0
        composeRule.setContent {
            M7_24Theme {
                ProfileReviewCard(
                    user = profileUser(
                        name = "Ayşe Demir",
                        reviewStatus = "confirmed",
                    ),
                    profile = CandidateProfileDto(
                        name = "Ayşe Demir",
                    ),
                    nameInput = "Ayşe Demir",
                    isEditing = false,
                    isSaving = false,
                    successMessage = null,
                    errorMessage = null,
                    onNameChange = {},
                    onEdit = { edits += 1 },
                    onCancel = {},
                    onSave = {},
                )
            }
        }

        composeRule.onNodeWithText("Ad doğrulandı")
            .assertIsDisplayed()
        composeRule.onNodeWithText("Ayşe Demir")
            .assertIsDisplayed()
        composeRule.onNodeWithText("Düzenle")
            .performClick()
        composeRule.runOnIdle {
            assertEquals(1, edits)
        }
    }

    @Test
    fun jobApplicationHistoryShowsLatestEmployerNote() {
        var withdrawnApplicationId = ""
        var interviewResponseApplicationId = ""
        var interviewResponseStatus = ""
        var interviewResponseNote = ""
        composeRule.setContent {
            M7_24Theme {
                JobApplicationsSection(
                    applications = listOf(
                        JobApplicationDto(
                            id = "application-1",
                            status = "shortlisted",
                            job = JobApplicationJobDto(
                                title = "Kaynak Operatörü",
                                company = "ACME Üretim",
                                location = "Kocaeli",
                            ),
                            statusHistory = listOf(
                                JobApplicationStatusHistoryDto(
                                    status = "shortlisted",
                                    note = "Telefon görüşmesi planlanacak.",
                                )
                            ),
                            interview = JobApplicationInterviewDto(
                                scheduledAt =
                                    "2026-08-01T07:30:00+00:00",
                                type = "video",
                                location =
                                    "Bağlantı SMS ile iletilecek",
                                note = "10 dakika önce hazır olun.",
                            ),
                        )
                    ),
                    onWithdraw = {
                        withdrawnApplicationId = it
                    },
                    onInterviewResponse = {
                            applicationId,
                            status,
                            note,
                        ->
                        interviewResponseApplicationId =
                            applicationId
                        interviewResponseStatus = status
                        interviewResponseNote = note
                    },
                )
            }
        }

        composeRule.onNodeWithText("Başvurularım")
            .assertIsDisplayed()
        composeRule.onNodeWithText("Kaynak Operatörü")
            .assertIsDisplayed()
        composeRule.onNodeWithText("Ön listeye alındı")
            .assertIsDisplayed()
        composeRule.onNodeWithText(
            "Telefon görüşmesi planlanacak."
        ).assertIsDisplayed()
        composeRule.onNodeWithTag(
            "job_application_interview_application-1"
        ).assertIsDisplayed()
        composeRule.onNodeWithText("Görüşme Planı")
            .assertIsDisplayed()
        composeRule.onNodeWithText("Video görüşme")
            .assertIsDisplayed()
        composeRule.onNodeWithText(
            "Konum: Bağlantı SMS ile iletilecek"
        ).assertIsDisplayed()
        composeRule.onNodeWithText(
            "10 dakika önce hazır olun."
        ).assertIsDisplayed()
        composeRule.onNodeWithTag(
            "job_application_interview_confirm_application-1"
        ).performClick()
        composeRule.onNodeWithTag(
            "job_application_interview_response_confirm"
        ).performClick()
        composeRule.runOnIdle {
            assertEquals(
                "application-1",
                interviewResponseApplicationId,
            )
            assertEquals("confirmed", interviewResponseStatus)
            assertEquals("", interviewResponseNote)
        }
        composeRule.onNodeWithTag(
            "job_application_interview_decline_application-1"
        ).performClick()
        composeRule.onNodeWithTag(
            "job_application_interview_response_confirm"
        ).assertIsNotEnabled()
        composeRule.onNodeWithTag(
            "job_application_interview_response_note"
        ).performTextInput("Vardiyadayım.")
        composeRule.onNodeWithTag(
            "job_application_interview_response_confirm"
        ).assertIsEnabled().performClick()
        composeRule.runOnIdle {
            assertEquals("declined", interviewResponseStatus)
            assertEquals("Vardiyadayım.", interviewResponseNote)
        }
        composeRule.onNodeWithTag(
            "job_application_withdraw_application-1"
        ).performClick()
        composeRule.onNodeWithText("Başvuruyu geri çek")
            .assertIsDisplayed()
        composeRule.runOnIdle {
            assertEquals("", withdrawnApplicationId)
        }
        composeRule.onNodeWithTag(
            "job_application_withdraw_confirm"
        ).performClick()
        composeRule.runOnIdle {
            assertEquals(
                "application-1",
                withdrawnApplicationId,
            )
        }
    }

    @Test
    fun failedAssessmentCanBeRetried() {
        var completedAssessmentId = ""
        var selectedOptionId = ""
        composeRule.setContent {
            M7_24Theme {
                WorkerHubSection(
                    hub = WorkerHubDto(
                        employerKey = "default",
                        assessments = listOf(
                            AssessmentDto(
                                id = "assessment-1",
                                title = "Güvenlik Kontrolü",
                                status = "completed",
                                score = 40,
                                passScore = 70,
                                passed = false,
                                attemptCount = 1,
                                questions = listOf(
                                    AssessmentQuestionDto(
                                        id = "question-1",
                                        prompt = "Doğru adım nedir?",
                                        options = listOf(
                                            AssessmentOptionDto(
                                                id = "option-1",
                                                label = "Sorumluya bildir",
                                            ),
                                            AssessmentOptionDto(
                                                id = "option-2",
                                                label = "Devam et",
                                            ),
                                        ),
                                    )
                                ),
                            )
                        ),
                    ),
                    question = "",
                    answer = null,
                    isAsking = false,
                    onQuestionChange = {},
                    onAskQuestion = {},
                    actionMessage = null,
                    activeActionKey = null,
                    onCompleteAssessment = {
                            assessmentId,
                            answers,
                        ->
                        completedAssessmentId = assessmentId
                        selectedOptionId =
                            answers.single().optionId
                    },
                    onSaveTrainingProgress = { _, _ -> },
                    onRequestShuttle = { _, _ -> },
                    onCancelShuttle = {},
                )
            }
        }

        composeRule.onNodeWithText("Tekrar gerekli")
            .assertIsDisplayed()
        composeRule.onNodeWithText("Deneme sayısı: 1")
            .assertIsDisplayed()
        composeRule.onNodeWithTag(
            "assessment_option_assessment-1_" +
                "question-1_option-1"
        ).performClick()
        composeRule.onNodeWithText("Tekrar Gönder")
            .assertIsEnabled()
            .performClick()
        composeRule.runOnIdle {
            assertEquals("assessment-1", completedAssessmentId)
            assertEquals("option-1", selectedOptionId)
        }
    }

    @Test
    fun partialTrainingProgressCanBeSaved() {
        var savedTrainingId = ""
        var savedModules = emptyList<String>()
        composeRule.setContent {
            M7_24Theme {
                WorkerHubSection(
                    hub = WorkerHubDto(
                        employerKey = "default",
                        trainings = listOf(
                            TrainingDto(
                                id = "training-1",
                                title = "Temel Eğitim",
                                status = "available",
                                modules = listOf(
                                    TrainingModuleDto(
                                        id = "module-1",
                                        title = "Birinci Modül",
                                    ),
                                    TrainingModuleDto(
                                        id = "module-2",
                                        title = "İkinci Modül",
                                    ),
                                ),
                            )
                        ),
                    ),
                    question = "",
                    answer = null,
                    isAsking = false,
                    onQuestionChange = {},
                    onAskQuestion = {},
                    actionMessage = null,
                    activeActionKey = null,
                    onCompleteAssessment = { _, _ -> },
                    onSaveTrainingProgress = {
                            trainingId,
                            moduleIds,
                        ->
                        savedTrainingId = trainingId
                        savedModules = moduleIds
                    },
                    onRequestShuttle = { _, _ -> },
                    onCancelShuttle = {},
                )
            }
        }

        composeRule.onNodeWithTag(
            "training_module_training-1_module-1"
        ).performClick()
        composeRule.onNodeWithText("İlerlemeyi Kaydet")
            .assertIsEnabled()
            .performClick()
        composeRule.runOnIdle {
            assertEquals("training-1", savedTrainingId)
            assertEquals(listOf("module-1"), savedModules)
        }
    }

    @Test
    fun shuttleCancellationRequiresConfirmation() {
        var cancelledRequestId = ""
        composeRule.setContent {
            M7_24Theme {
                Column(
                    modifier = Modifier.verticalScroll(
                        rememberScrollState()
                    )
                ) {
                    WorkerHubSection(
                        hub = WorkerHubDto(
                            employerKey = "default",
                            shuttle = ShuttleDto(
                                enabled = true,
                                title = "Servis Planlama",
                                requestId = "request-1",
                                selectedRouteId = "route-1",
                                selectedRouteName = "Merkez - OSB",
                                requestStatus = "requested",
                                routes = listOf(
                                    ShuttleRouteDto(
                                        id = "route-1",
                                        name = "Merkez - OSB",
                                    )
                                ),
                            ),
                        ),
                        question = "",
                        answer = null,
                        isAsking = false,
                        onQuestionChange = {},
                        onAskQuestion = {},
                        actionMessage = null,
                        activeActionKey = null,
                        onCompleteAssessment = { _, _ -> },
                        onSaveTrainingProgress = { _, _ -> },
                        onRequestShuttle = { _, _ -> },
                        onCancelShuttle = {
                            cancelledRequestId = it
                        },
                    )
                }
            }
        }

        composeRule.onNodeWithTag("shuttle_cancel_open")
            .performScrollTo()
            .assertIsDisplayed()
            .performClick()
        composeRule.onNodeWithText("Servis talebini iptal et")
            .assertIsDisplayed()
        composeRule.runOnIdle {
            assertEquals("", cancelledRequestId)
        }
        composeRule.onNodeWithTag("shuttle_cancel_confirm")
            .performClick()
        composeRule.runOnIdle {
            assertEquals("request-1", cancelledRequestId)
        }
    }

    private fun profileUser(
        name: String,
        reviewStatus: String,
    ) = UserDto(
        id = "worker-profile",
        name = name,
        nameStatus = if (reviewStatus == "confirmed") {
            "confirmed_by_worker"
        } else {
            "inferred_from_video"
        },
        phone = "+905551112233",
        employerKey = "default",
        phoneVerifiedAt = null,
        profileStatus = "profile_ready",
        videoStatus = "completed",
        latestVideoId = "video-1",
        createdAt = null,
        updatedAt = null,
        profileReviewStatus = reviewStatus,
    )
}

@RunWith(AndroidJUnit4::class)
class SessionStoreInstrumentedTest {
    private lateinit var context: Context
    private lateinit var preferences: android.content.SharedPreferences

    @Before
    fun setUp() {
        context = InstrumentationRegistry.getInstrumentation().targetContext
        preferences = context.getSharedPreferences(
            SESSION_PREFERENCES,
            Context.MODE_PRIVATE,
        )
        preferences.edit().clear().commit()
    }

    @After
    fun tearDown() {
        preferences.edit().clear().commit()
    }

    @Test
    fun accessTokenIsEncryptedAndCanBeRestored() {
        val token = "worker-access-token-that-must-not-be-plaintext"
        val store = SessionStore(context)

        store.saveAuth(testUser(), token)

        val persistedValue = preferences.getString(
            ACCESS_TOKEN_KEY,
            null,
        )
        assertEquals("worker-1", store.getUserId())
        assertEquals(token, store.getAccessToken())
        assertNotEquals(token, persistedValue)
        assertFalse(persistedValue.orEmpty().contains(token))
    }

    @Test
    fun corruptedEncryptedTokenIsRejectedAndRemoved() {
        preferences.edit()
            .putString(ACCESS_TOKEN_KEY, "not-valid-ciphertext")
            .commit()
        val store = SessionStore(context)

        assertNull(store.getAccessToken())
        assertFalse(preferences.contains(ACCESS_TOKEN_KEY))
    }

    private fun testUser() = UserDto(
        id = "worker-1",
        name = "Test Kullanıcı",
        nameStatus = "inferred_from_video",
        phone = "+905551112233",
        employerKey = "default",
        phoneVerifiedAt = null,
        profileStatus = "profile_ready",
        videoStatus = "completed",
        latestVideoId = "video-1",
        createdAt = null,
        updatedAt = null,
    )

    private companion object {
        const val SESSION_PREFERENCES = "m7_24_session"
        const val ACCESS_TOKEN_KEY = "access_token"
    }
}

@RunWith(AndroidJUnit4::class)
class DashboardNotificationStoreInstrumentedTest {
    private lateinit var store: DashboardNotificationStore

    @Before
    fun setUp() {
        val context =
            InstrumentationRegistry.getInstrumentation().targetContext
        store = DashboardNotificationStore(context)
        store.clear()
    }

    @After
    fun tearDown() {
        store.clear()
    }

    @Test
    fun notificationSnapshotCanBeRestoredAndCleared() {
        val snapshot = DashboardNotificationSnapshot(
            applications = mapOf(
                "application-1" to ApplicationNotificationState(
                    id = "application-1",
                    status = "reviewing",
                    title = "Kaynak Operatörü",
                )
            ),
            shuttle = ShuttleNotificationState(
                status = "confirmed",
                routeName = "Merkez Hattı",
                decisionNote = "Listeye eklendi.",
            ),
            answeredQuestions = mapOf(
                "question-1" to "Servis saatim nedir?"
            ),
        )

        store.save(snapshot)

        assertEquals(
            snapshot.copy(
                answeredQuestions = mapOf(
                    "question-1" to "",
                ),
            ),
            store.load(),
        )
        store.clear()
        assertNull(store.load())
    }

    @Test
    fun directPushUpdatesPollingBaseline() {
        store.save(
            DashboardNotificationSnapshot(
                applications = mapOf(
                    "application-1" to ApplicationNotificationState(
                        id = "application-1",
                        status = "reviewing",
                        title = "Kaynak Operatörü",
                    )
                ),
                shuttle = ShuttleNotificationState(
                    status = "requested",
                    routeName = "Merkez Hattı",
                    decisionNote = "",
                ),
                answeredQuestions = emptyMap(),
            )
        )

        store.applyPushEvent(
            WorkerPushPayload(
                eventId = "application-event",
                eventType = "application_status",
                title = "Başvuru güncellendi",
                body = "Kısa listede",
                entityId = "application-1",
                status = "shortlisted",
                routeName = "",
            )
        )
        store.applyPushEvent(
            WorkerPushPayload(
                eventId = "question-event",
                eventType = "question_answered",
                title = "Sorunuz yanıtlandı",
                body = "Yanıtı görüntüleyin.",
                entityId = "question-1",
                status = "answered",
                routeName = "",
            )
        )
        store.applyPushEvent(
            WorkerPushPayload(
                eventId = "shuttle-event",
                eventType = "shuttle_status",
                title = "Servis güncellendi",
                body = "Onaylandı",
                entityId = "shuttle-1",
                status = "confirmed",
                routeName = "Merkez Hattı",
            )
        )

        val updated = store.load()
        assertEquals(
            "shortlisted",
            updated?.applications?.get("application-1")?.status,
        )
        assertEquals(
            "Kaynak Operatörü",
            updated?.applications?.get("application-1")?.title,
        )
        assertTrue(
            "question-1" in updated?.answeredQuestions.orEmpty()
        )
        assertEquals("confirmed", updated?.shuttle?.status)

        val polled = DashboardNotificationSnapshot(
            applications = updated?.applications.orEmpty(),
            shuttle = updated?.shuttle,
            answeredQuestions = updated?.answeredQuestions.orEmpty(),
        )
        assertTrue(
            dashboardNotificationEvents(updated, polled).isEmpty()
        )
    }
}

@RunWith(AndroidJUnit4::class)
class PushRegistrationStoreInstrumentedTest {
    private lateinit var context: Context
    private lateinit var pushEventStore: PushEventStore

    @Before
    fun setUp() {
        context =
            InstrumentationRegistry.getInstrumentation().targetContext
        pushEventStore = PushEventStore(context)
        pushEventStore.clear()
    }

    @After
    fun tearDown() {
        pushEventStore.clear()
    }

    @Test
    fun installationIdIsStableAndCanonical() {
        val store = InstallationStore(context)

        val first = store.getOrCreateId()
        val second = store.getOrCreateId()

        assertEquals(first, second)
        assertEquals(first, java.util.UUID.fromString(first).toString())
    }

    @Test
    fun pushEventsArePersistentlyDeduplicated() {
        assertTrue(pushEventStore.markIfNew("event-1"))
        assertFalse(pushEventStore.markIfNew("event-1"))
        assertTrue(pushEventStore.markIfNew("event-2"))
        assertFalse(PushEventStore(context).markIfNew("event-2"))
    }
}
