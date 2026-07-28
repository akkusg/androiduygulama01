package com.example.m7_24.api

data class MobileConfigResponse(
    val platform: String,
    val minSupportedVersionCode: Int,
    val latestVersionCode: Int,
    val maintenanceMode: Boolean,
    val maintenanceMessage: String,
    val updateMessage: String,
    val updateUrl: String,
    val privacyPolicyUrl: String = "",
    val videoConsentVersion: String = "",
)

data class OtpRequest(
    val phone: String
)

data class OtpChallengeResponse(
    val challengeId: String,
    val phone: String,
    val expiresIn: Int,
    val resendAfterSeconds: Int,
    val devCode: String? = null
)

data class OtpVerifyRequest(
    val challengeId: String,
    val phone: String,
    val code: String
)

data class AuthResponse(
    val accessToken: String,
    val tokenType: String,
    val expiresIn: Int,
    val user: UserDto
)

data class AskQuestionRequest(
    val question: String
)

data class CompleteAssessmentRequest(
    val answers: List<AssessmentAnswerRequest> = emptyList()
)

data class AssessmentAnswerRequest(
    val questionId: String,
    val optionId: String
)

data class CompleteTrainingRequest(
    val completedModules: List<String> = emptyList()
)

data class UpdateTrainingProgressRequest(
    val completedModules: List<String> = emptyList()
)

data class ShuttleRequestRequest(
    val routeId: String,
    val pickupNote: String = ""
)

data class JobApplicationRequest(
    val jobRecommendationId: String,
    val coverNote: String = ""
)

data class ProfileReviewRequest(
    val name: String,
)

data class ProfileReviewResponse(
    val user: UserDto,
    val candidateProfile: CandidateProfileDto,
)

data class VideoConsentRequest(
    val version: String,
    val accepted: Boolean = true,
)

data class VideoConsentResponse(
    val consent: VideoConsentDto,
)

data class VideoConsentDto(
    val id: String? = null,
    val type: String = "video_processing",
    val version: String,
    val status: String,
    val policyUrl: String = "",
    val acceptedAt: String? = null,
    val revokedAt: String? = null,
    val appVersionCode: String? = null,
    val appVersionName: String? = null,
)

data class DeviceRegistrationRequest(
    val fid: String,
    val platform: String = "android",
    val appVersionCode: Int,
    val appVersionName: String,
)

data class DeviceResponse(
    val device: DeviceDto,
)

data class DeviceDto(
    val id: String,
    val installationId: String,
    val platform: String,
    val appVersionCode: Int,
    val appVersionName: String,
    val active: Boolean,
    val lastSeenAt: String?,
)

data class UserResponse(
    val user: UserDto
)

data class VideoResponse(
    val video: VideoDto
)

data class QuestionResponse(
    val answer: WorkerAnswerDto
)

data class AssessmentCompletionResponse(
    val assessment: AssessmentResultDto
)

data class TrainingCompletionResponse(
    val training: TrainingProgressDto
)

data class ShuttleRequestResponse(
    val shuttleRequest: ShuttleRequestDto
)

data class JobApplicationResponse(
    val jobApplication: JobApplicationDto
)

data class DashboardResponse(
    val user: UserDto,
    val latestVideo: VideoDto?,
    val latestTranscript: TranscriptDto?,
    val candidateProfile: CandidateProfileDto?,
    val recommendedJobs: List<JobDto>,
    val jobApplications: List<JobApplicationDto> = emptyList(),
    val workerHub: WorkerHubDto?,
    val videoConsent: VideoConsentDto? = null,
    val recentQuestions: List<WorkerQuestionDto> = emptyList(),
    val pendingQuestionCount: Int = 0
)

data class UserDto(
    val id: String,
    val name: String,
    val nameStatus: String?,
    val phone: String,
    val employerKey: String?,
    val phoneVerifiedAt: String?,
    val profileStatus: String,
    val videoStatus: String,
    val latestVideoId: String?,
    val createdAt: String?,
    val updatedAt: String?,
    val profileReviewStatus: String? = null,
    val profileReviewedAt: String? = null,
)

data class VideoDto(
    val id: String,
    val userId: String,
    val originalFilename: String,
    val contentType: String?,
    val status: String,
    val createdAt: String?,
    val updatedAt: String?,
    val consentVersion: String? = null,
    val consentAcceptedAt: String? = null,
)

data class JobDto(
    val id: String? = null,
    val jobPostingId: String? = null,
    val title: String? = null,
    val company: String? = null,
    val location: String? = null,
    val matchScore: Int? = null,
    val reason: String? = null,
    val requiredSkills: List<String> = emptyList(),
    val applicationId: String? = null,
    val applicationStatus: String? = null,
    val appliedAt: String? = null
)

data class CandidateProfileDto(
    val name: String? = null,
    val nameSource: String? = null,
    val nameReviewedAt: String? = null,
    val summary: String? = null,
    val skills: List<String> = emptyList(),
    val preferredRoles: List<String> = emptyList(),
    val confidence: Double? = null,
    val warnings: List<String> = emptyList()
)

data class TranscriptDto(
    val provider: String? = null,
    val status: String? = null,
    val text: String? = null,
    val warnings: List<String> = emptyList()
)

data class WorkerHubDto(
    val employerKey: String? = null,
    val assessments: List<AssessmentDto> = emptyList(),
    val trainings: List<TrainingDto> = emptyList(),
    val usefulInfo: List<UsefulInfoDto> = emptyList(),
    val shuttle: ShuttleDto? = null
)

data class AssessmentDto(
    val id: String? = null,
    val title: String? = null,
    val description: String? = null,
    val status: String? = null,
    val durationMinutes: Int? = null,
    val required: Boolean = false,
    val passScore: Int? = null,
    val questions: List<AssessmentQuestionDto> = emptyList(),
    val score: Int? = null,
    val passed: Boolean? = null,
    val answers: List<AssessmentAnswerDto> = emptyList(),
    val attemptCount: Int? = null,
    val completedAt: String? = null
)

data class AssessmentQuestionDto(
    val id: String? = null,
    val prompt: String? = null,
    val options: List<AssessmentOptionDto> = emptyList()
)

data class AssessmentOptionDto(
    val id: String? = null,
    val label: String? = null,
    val score: Int? = null
)

data class AssessmentAnswerDto(
    val questionId: String? = null,
    val optionId: String? = null
)

data class TrainingDto(
    val id: String? = null,
    val title: String? = null,
    val description: String? = null,
    val durationMinutes: Int? = null,
    val status: String? = null,
    val modules: List<TrainingModuleDto> = emptyList(),
    val progressPercent: Int? = null,
    val completedModules: List<String> = emptyList(),
    val completedAt: String? = null
)

data class TrainingModuleDto(
    val id: String? = null,
    val title: String? = null,
    val body: String? = null
)

data class UsefulInfoDto(
    val id: String? = null,
    val title: String? = null,
    val body: String? = null,
    val category: String? = null
)

data class ShuttleDto(
    val enabled: Boolean = false,
    val title: String? = null,
    val description: String? = null,
    val routes: List<ShuttleRouteDto> = emptyList(),
    val requestId: String? = null,
    val selectedRouteId: String? = null,
    val selectedRouteName: String? = null,
    val requestStatus: String? = null,
    val pickupNote: String? = null,
    val decisionNote: String? = null,
    val requestedAt: String? = null
)

data class ShuttleRouteDto(
    val id: String? = null,
    val name: String? = null,
    val pickupWindow: String? = null
)

data class WorkerAnswerDto(
    val question: String? = null,
    val answer: String? = null,
    val matchedKeywords: List<String> = emptyList()
)

data class WorkerQuestionDto(
    val id: String? = null,
    val question: String? = null,
    val answer: String? = null,
    val status: String? = null,
    val matchedKeywords: List<String> = emptyList(),
    val createdAt: String? = null
)

data class AssessmentResultDto(
    val assessmentId: String? = null,
    val title: String? = null,
    val status: String? = null,
    val score: Int? = null,
    val passScore: Int? = null,
    val passed: Boolean? = null,
    val answers: List<AssessmentAnswerDto> = emptyList(),
    val attemptCount: Int? = null,
    val attemptHistory: List<AssessmentAttemptDto> = emptyList()
)

data class AssessmentAttemptDto(
    val score: Int? = null,
    val passScore: Int? = null,
    val passed: Boolean? = null,
    val answers: List<AssessmentAnswerDto> = emptyList(),
    val completedAt: String? = null
)

data class TrainingProgressDto(
    val trainingId: String? = null,
    val title: String? = null,
    val status: String? = null,
    val progressPercent: Int? = null,
    val completedModules: List<String> = emptyList()
)

data class ShuttleRequestDto(
    val routeId: String? = null,
    val routeName: String? = null,
    val pickupWindow: String? = null,
    val pickupNote: String? = null,
    val decisionNote: String? = null,
    val status: String? = null
)

data class JobApplicationDto(
    val id: String? = null,
    val userId: String? = null,
    val jobRecommendationId: String? = null,
    val jobPostingId: String? = null,
    val employerKey: String? = null,
    val status: String? = null,
    val coverNote: String? = null,
    val job: JobApplicationJobDto = JobApplicationJobDto(),
    val candidate: JobApplicationCandidateDto = JobApplicationCandidateDto(),
    val statusHistory: List<JobApplicationStatusHistoryDto> = emptyList(),
    val interview: JobApplicationInterviewDto? = null,
    val withdrawnAt: String? = null,
    val createdAt: String? = null,
    val updatedAt: String? = null
)

data class JobApplicationInterviewDto(
    val scheduledAt: String? = null,
    val type: String? = null,
    val location: String? = null,
    val note: String? = null,
    val updatedAt: String? = null
)

data class JobApplicationStatusHistoryDto(
    val status: String? = null,
    val note: String? = null,
    val changedAt: String? = null
)

data class JobApplicationJobDto(
    val title: String? = null,
    val company: String? = null,
    val location: String? = null,
    val matchScore: Int? = null
)

data class JobApplicationCandidateDto(
    val name: String? = null,
    val phone: String? = null,
    val profileStatus: String? = null,
    val skills: List<String> = emptyList(),
    val summary: String? = null
)
