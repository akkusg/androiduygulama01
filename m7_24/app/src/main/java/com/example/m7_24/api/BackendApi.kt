package com.example.m7_24.api

import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.PUT

interface BackendApi {
    @GET("api/mobile-config")
    suspend fun getMobileConfig(): MobileConfigResponse

    @POST("api/auth/otp/request")
    suspend fun requestOtp(@Body request: OtpRequest): OtpChallengeResponse

    @POST("api/auth/otp/verify")
    suspend fun verifyOtp(@Body request: OtpVerifyRequest): AuthResponse

    @POST("api/auth/logout")
    suspend fun logout()

    @DELETE("api/users/{userId}")
    suspend fun deleteAccount(@Path("userId") userId: String)

    @PUT("api/users/{userId}/devices/{installationId}")
    suspend fun registerDevice(
        @Path("userId") userId: String,
        @Path("installationId") installationId: String,
        @Body request: DeviceRegistrationRequest,
    ): DeviceResponse

    @DELETE("api/users/{userId}/devices/{installationId}")
    suspend fun unregisterDevice(
        @Path("userId") userId: String,
        @Path("installationId") installationId: String,
    )

    @PUT("api/users/{userId}/profile-review")
    suspend fun reviewProfile(
        @Path("userId") userId: String,
        @Body request: ProfileReviewRequest,
    ): ProfileReviewResponse

    @GET("api/users/{userId}/consents/video-processing")
    suspend fun getVideoConsent(
        @Path("userId") userId: String,
    ): VideoConsentResponse

    @PUT("api/users/{userId}/consents/video-processing")
    suspend fun acceptVideoConsent(
        @Path("userId") userId: String,
        @Body request: VideoConsentRequest,
    ): VideoConsentResponse

    @DELETE("api/users/{userId}/consents/video-processing")
    suspend fun withdrawVideoConsent(
        @Path("userId") userId: String,
    ): VideoConsentResponse

    @GET("api/users/{userId}/data-export")
    suspend fun exportAccountData(
        @Path("userId") userId: String
    ): ResponseBody

    @Multipart
    @POST("api/users/{userId}/videos")
    suspend fun uploadVideo(
        @Path("userId") userId: String,
        @Part video: MultipartBody.Part,
        @Header("Idempotency-Key") idempotencyKey: String,
        @Header("X-Upload-SHA256") uploadSha256: String,
    ): VideoResponse

    @GET("api/users/{userId}/dashboard")
    suspend fun getDashboard(@Path("userId") userId: String): DashboardResponse

    @POST("api/users/{userId}/questions")
    suspend fun askQuestion(
        @Path("userId") userId: String,
        @Body request: AskQuestionRequest,
        @Header("Idempotency-Key") idempotencyKey: String
    ): QuestionResponse

    @POST("api/users/{userId}/assessments/{assessmentId}/complete")
    suspend fun completeAssessment(
        @Path("userId") userId: String,
        @Path("assessmentId") assessmentId: String,
        @Body request: CompleteAssessmentRequest = CompleteAssessmentRequest(),
        @Header("Idempotency-Key") idempotencyKey: String
    ): AssessmentCompletionResponse

    @POST("api/users/{userId}/trainings/{trainingId}/complete")
    suspend fun completeTraining(
        @Path("userId") userId: String,
        @Path("trainingId") trainingId: String,
        @Body request: CompleteTrainingRequest = CompleteTrainingRequest(),
        @Header("Idempotency-Key") idempotencyKey: String
    ): TrainingCompletionResponse

    @PUT("api/users/{userId}/trainings/{trainingId}/progress")
    suspend fun saveTrainingProgress(
        @Path("userId") userId: String,
        @Path("trainingId") trainingId: String,
        @Body request: UpdateTrainingProgressRequest,
        @Header("Idempotency-Key") idempotencyKey: String
    ): TrainingCompletionResponse

    @POST("api/users/{userId}/shuttle-requests")
    suspend fun requestShuttle(
        @Path("userId") userId: String,
        @Body request: ShuttleRequestRequest,
        @Header("Idempotency-Key") idempotencyKey: String
    ): ShuttleRequestResponse

    @POST("api/users/{userId}/shuttle-requests/{requestId}/cancel")
    suspend fun cancelShuttle(
        @Path("userId") userId: String,
        @Path("requestId") requestId: String,
        @Header("Idempotency-Key") idempotencyKey: String
    ): ShuttleRequestResponse

    @POST("api/users/{userId}/job-applications")
    suspend fun applyToJob(
        @Path("userId") userId: String,
        @Body request: JobApplicationRequest,
        @Header("Idempotency-Key") idempotencyKey: String
    ): JobApplicationResponse

    @POST(
        "api/users/{userId}/job-applications/" +
            "{applicationId}/withdraw"
    )
    suspend fun withdrawJobApplication(
        @Path("userId") userId: String,
        @Path("applicationId") applicationId: String,
        @Header("Idempotency-Key") idempotencyKey: String
    ): JobApplicationResponse
}
