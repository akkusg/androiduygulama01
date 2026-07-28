package com.example.m7_24

import android.Manifest
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Recording
import androidx.camera.video.VideoRecordEvent
import androidx.camera.view.CameraController
import androidx.camera.view.LifecycleCameraController
import androidx.camera.view.video.AudioConfig
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Create
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.example.m7_24.api.BackendClient
import com.example.m7_24.api.AskQuestionRequest
import com.example.m7_24.api.AssessmentAnswerRequest
import com.example.m7_24.api.CompleteAssessmentRequest
import com.example.m7_24.api.CandidateProfileDto
import com.example.m7_24.api.DashboardResponse
import com.example.m7_24.api.JobApplicationDto
import com.example.m7_24.api.JobApplicationRequest
import com.example.m7_24.api.JobDto
import com.example.m7_24.api.MobileConfigResponse
import com.example.m7_24.api.OtpRequest
import com.example.m7_24.api.OtpVerifyRequest
import com.example.m7_24.api.ProfileReviewRequest
import com.example.m7_24.api.ShuttleRequestRequest
import com.example.m7_24.api.UpdateTrainingProgressRequest
import com.example.m7_24.api.UserDto
import com.example.m7_24.api.VideoConsentRequest
import com.example.m7_24.api.WorkerHubDto
import com.example.m7_24.api.WorkerQuestionDto
import com.example.m7_24.ui.theme.M7_24Theme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

private const val VIDEO_PROCESSING_REFRESH_MS = 2_000L
private const val PENDING_QUESTION_REFRESH_MS = 15_000L
private const val ACTIVE_WORKFLOW_REFRESH_MS = 60_000L
private const val VIDEO_RECORDING_MAX_DURATION_MS = 90_000L
private const val VIDEO_RECORDING_MAX_FILE_SIZE_BYTES = 150L * 1024 * 1024
private val ACTIVE_JOB_APPLICATION_STATUSES = setOf(
    "submitted",
    "reviewing",
    "shortlisted",
)

private sealed interface MobileGateState {
    data object Loading : MobileGateState
    data class Ready(
        val config: MobileConfigResponse,
    ) : MobileGateState
    data class Blocked(
        val availability: AppAvailability,
        val config: MobileConfigResponse,
    ) : MobileGateState
    data object ConnectionError : MobileGateState
}

private sealed interface VideoConsentGateState {
    data object Loading : VideoConsentGateState
    data object Required : VideoConsentGateState
    data object Accepted : VideoConsentGateState
    data object ConnectionError : VideoConsentGateState
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            M7_24Theme {
                MobileConfigGate { config ->
                    AppNavigation(config)
                }
            }
        }
    }
}

@Composable
private fun MobileConfigGate(
    content: @Composable (MobileConfigResponse) -> Unit,
) {
    val context = LocalContext.current
    var retryAttempt by rememberSaveable { mutableIntStateOf(0) }
    var state by remember {
        mutableStateOf<MobileGateState>(MobileGateState.Loading)
    }

    LaunchedEffect(retryAttempt) {
        state = MobileGateState.Loading
        state = try {
            val config = BackendClient.api.getMobileConfig()
            when (
                val availability = evaluateAppAvailability(
                    config = config,
                    installedVersionCode = BuildConfig.VERSION_CODE,
                )
            ) {
                AppAvailability.Available -> MobileGateState.Ready(
                    config,
                )
                else -> MobileGateState.Blocked(
                    availability,
                    config,
                )
            }
        } catch (_: Exception) {
            MobileGateState.ConnectionError
        }
    }

    when (val currentState = state) {
        MobileGateState.Loading -> {
            AppAvailabilityScreen(
                title = "Uygulama hazırlanıyor",
                message = "Sunucu bağlantısı kontrol ediliyor.",
                showProgress = true,
            )
        }

        is MobileGateState.Ready -> content(currentState.config)
        MobileGateState.ConnectionError -> {
            AppAvailabilityScreen(
                title = "Bağlantı kurulamadı",
                message = "İnternet bağlantınızı kontrol edip tekrar deneyin.",
                onRetry = { retryAttempt += 1 },
            )
        }

        is MobileGateState.Blocked -> {
            when (val availability = currentState.availability) {
                AppAvailability.Available -> content(
                    currentState.config
                )
                is AppAvailability.Maintenance -> {
                    AppAvailabilityScreen(
                        title = "Bakım çalışması",
                        message = availability.message,
                        onRetry = { retryAttempt += 1 },
                    )
                }

                is AppAvailability.UpdateRequired -> {
                    AppAvailabilityScreen(
                        title = "Güncelleme gerekli",
                        message = availability.message,
                        updateUrl = availability.updateUrl,
                        onRetry = { retryAttempt += 1 },
                        onUpdate = {
                            runCatching {
                                context.startActivity(
                                    Intent(
                                        Intent.ACTION_VIEW,
                                        Uri.parse(availability.updateUrl),
                                    )
                                )
                            }
                        },
                    )
                }
            }
        }
    }
}

@Composable
internal fun AppAvailabilityScreen(
    title: String,
    message: String,
    showProgress: Boolean = false,
    updateUrl: String = "",
    onRetry: (() -> Unit)? = null,
    onUpdate: (() -> Unit)? = null,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.headlineSmall,
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (showProgress) {
                Spacer(modifier = Modifier.height(24.dp))
                CircularProgressIndicator(
                    modifier = Modifier.testTag("mobile_gate_loading"),
                )
            }
            if (onUpdate != null && updateUrl.isNotBlank()) {
                Spacer(modifier = Modifier.height(24.dp))
                Button(
                    onClick = onUpdate,
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("mobile_gate_update"),
                ) {
                    Text("Uygulamayı Güncelle")
                }
            }
            if (onRetry != null) {
                Spacer(modifier = Modifier.height(12.dp))
                OutlinedButton(
                    onClick = onRetry,
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("mobile_gate_retry"),
                ) {
                    Icon(
                        Icons.Default.Refresh,
                        contentDescription = null,
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Tekrar Dene")
                }
            }
        }
    }
}

sealed class Screen(val route: String) {
    object Registration : Screen("registration")
    object Onboarding : Screen("onboarding")
    object VideoRecord : Screen("video_record")
    object Upload : Screen("upload/{videoUri}") {
        fun createRoute(videoUri: String) = "upload/$videoUri"
    }
    object Dashboard : Screen("dashboard")
}

@Composable
fun AppNavigation(mobileConfig: MobileConfigResponse) {
    val context = LocalContext.current
    val sessionStore = remember { SessionStore(context) }
    val initialUserId = remember { sessionStore.getUserId() }
    val initialAccessToken = remember { sessionStore.getAccessToken() }
    val navController = rememberNavController()
    var currentUserId by rememberSaveable { mutableStateOf(initialUserId) }
    val coroutineScope = rememberCoroutineScope()
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    LaunchedEffect(initialUserId, initialAccessToken) {
        withContext(Dispatchers.IO) {
            if (initialUserId.isNullOrBlank() || initialAccessToken.isNullOrBlank()) {
                clearWorkerPrivateCache(context.cacheDir)
            } else {
                cleanupStaleCapturedVideos(context.cacheDir)
                cleanupStaleDataExports(context.cacheDir)
            }
        }
    }
    LaunchedEffect(initialAccessToken) {
        BackendClient.setAccessToken(initialAccessToken)
    }
    LaunchedEffect(currentUserId) {
        withContext(Dispatchers.IO) {
            if (
                currentUserId.isNullOrBlank() ||
                sessionStore.getAccessToken().isNullOrBlank()
            ) {
                WorkerNotificationScheduler.cancelAndClear(context)
            } else {
                WorkerNotificationScheduler.schedule(context)
                PushRegistrationScheduler.schedule(context)
            }
        }
    }
    val startDestination = remember {
        if (initialUserId.isNullOrBlank() || initialAccessToken.isNullOrBlank()) {
            Screen.Registration.route
        } else {
            Screen.Dashboard.route
        }
    }
    DisposableEffect(navController, sessionStore) {
        BackendClient.setUnauthorizedHandler {
            mainHandler.post {
                BackendClient.setAccessToken(null)
                sessionStore.clear()
                currentUserId = null
                coroutineScope.launch {
                    withContext(Dispatchers.IO) {
                        runCatching { unregisterLocalPush() }
                        clearWorkerPrivateCache(context.cacheDir)
                    }
                    if (
                        navController.currentDestination?.route
                        != Screen.Registration.route
                    ) {
                        navController.navigate(Screen.Registration.route) {
                            popUpTo(navController.graph.startDestinationId) {
                                inclusive = true
                            }
                            launchSingleTop = true
                        }
                    }
                }
            }
        }
        onDispose {
            BackendClient.setUnauthorizedHandler(null)
        }
    }

    NavHost(navController = navController, startDestination = startDestination) {
        composable(Screen.Registration.route) {
            RegistrationScreen(onRegisterSuccess = { user, accessToken ->
                sessionStore.saveAuth(user, accessToken)
                BackendClient.setAccessToken(accessToken)
                currentUserId = user.id
                val destination = if (user.videoStatus == "not_uploaded") {
                    Screen.Onboarding.route
                } else {
                    Screen.Dashboard.route
                }
                navController.navigate(destination) {
                    popUpTo(Screen.Registration.route) { inclusive = true }
                }
            })
        }
        composable(Screen.Onboarding.route) {
            VideoConsentGate(
                userId = currentUserId,
                consentVersion = mobileConfig.videoConsentVersion,
                privacyPolicyUrl = mobileConfig.privacyPolicyUrl,
            ) {
                OnboardingScreen(onVideoRecorded = { uri ->
                    val encodedUri = Uri.encode(uri.toString())
                    navController.navigate(
                        Screen.Upload.createRoute(encodedUri)
                    )
                })
            }
        }
        composable(Screen.VideoRecord.route) {
            VideoConsentGate(
                userId = currentUserId,
                consentVersion = mobileConfig.videoConsentVersion,
                privacyPolicyUrl = mobileConfig.privacyPolicyUrl,
            ) {
                VideoRecordScreen(onVideoRecorded = { uri ->
                    val encodedUri = Uri.encode(uri.toString())
                    navController.navigate(
                        Screen.Upload.createRoute(encodedUri)
                    )
                })
            }
        }
        composable(Screen.Upload.route) { backStackEntry ->
            val videoUri = backStackEntry.arguments?.getString("videoUri")
            UploadScreen(userId = currentUserId, videoUri = videoUri, onUploadComplete = {
                navController.navigate(Screen.Dashboard.route) {
                    popUpTo(Screen.Registration.route) { inclusive = true }
                }
            })
        }
        composable(Screen.Dashboard.route) {
            DashboardScreen(userId = currentUserId, onUpdateVideo = {
                navController.navigate(Screen.Onboarding.route)
            }, onAccountDeleted = {
                BackendClient.setAccessToken(null)
                sessionStore.clear()
                currentUserId = null
                coroutineScope.launch {
                    withContext(Dispatchers.IO) {
                        runCatching { unregisterLocalPush() }
                        clearWorkerPrivateCache(context.cacheDir)
                    }
                    navController.navigate(Screen.Registration.route) {
                        popUpTo(Screen.Dashboard.route) { inclusive = true }
                    }
                }
            }, onResetSession = {
                coroutineScope.launch {
                    val userId = currentUserId
                    runCatching {
                        unregisterPushDevice(context, userId)
                    }
                    runCatching { BackendClient.api.logout() }
                    runCatching { unregisterLocalPush() }
                    BackendClient.setAccessToken(null)
                    sessionStore.clear()
                    currentUserId = null
                    withContext(Dispatchers.IO) {
                        clearWorkerPrivateCache(context.cacheDir)
                    }
                    navController.navigate(Screen.Registration.route) {
                        popUpTo(Screen.Dashboard.route) { inclusive = true }
                    }
                }
            })
        }
    }
}

@Composable
fun RegistrationScreen(onRegisterSuccess: (UserDto, String) -> Unit) {
    var phone by rememberSaveable { mutableStateOf("") }
    var challengeId by rememberSaveable { mutableStateOf<String?>(null) }
    var verificationCode by rememberSaveable { mutableStateOf("") }
    var devCode by rememberSaveable { mutableStateOf<String?>(null) }
    var resendAvailableAtMillis by rememberSaveable {
        mutableLongStateOf(0L)
    }
    var resendSecondsRemaining by remember {
        mutableIntStateOf(0)
    }
    var isSubmitting by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    val coroutineScope = rememberCoroutineScope()

    LaunchedEffect(challengeId, resendAvailableAtMillis) {
        if (challengeId == null) {
            resendSecondsRemaining = 0
            return@LaunchedEffect
        }
        do {
            val remainingMillis =
                resendAvailableAtMillis - System.currentTimeMillis()
            resendSecondsRemaining = if (remainingMillis > 0) {
                ((remainingMillis + 999) / 1_000).toInt()
            } else {
                0
            }
            if (resendSecondsRemaining > 0) delay(250)
        } while (resendSecondsRemaining > 0)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(text = "Telefonunuzu Doğrulayın", style = MaterialTheme.typography.headlineMedium)
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = if (challengeId == null) {
                "Kayıt ve giriş için telefon numaranızı yazın."
            } else {
                "$phone numarasına gönderilen 6 haneli kodu girin."
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(modifier = Modifier.height(16.dp))
        OutlinedTextField(
            value = phone,
            onValueChange = {
                phone = it
                errorMessage = null
            },
            label = { Text("Telefon Numarası") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
            enabled = challengeId == null && !isSubmitting,
            modifier = Modifier
                .fillMaxWidth()
                .testTag("phone_input")
        )
        if (challengeId != null) {
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedTextField(
                value = verificationCode,
                onValueChange = { value ->
                    verificationCode = value.filter(Char::isDigit).take(6)
                    errorMessage = null
                },
                label = { Text("Doğrulama Kodu") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                singleLine = true,
                enabled = !isSubmitting,
                modifier = Modifier.fillMaxWidth()
            )
            if (!devCode.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Geliştirme kodu: ${devCode.orEmpty()}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary
                )
            }
            TextButton(
                onClick = {
                    coroutineScope.launch {
                        isSubmitting = true
                        errorMessage = null
                        try {
                            val response = BackendClient.api.requestOtp(
                                OtpRequest(phone = phone.trim())
                            )
                            phone = response.phone
                            challengeId = response.challengeId
                            devCode = response.devCode
                            verificationCode =
                                response.devCode.orEmpty()
                            resendAvailableAtMillis =
                                System.currentTimeMillis() +
                                    response.resendAfterSeconds * 1_000L
                        } catch (error: Exception) {
                            error.retryAfterSeconds()?.let { seconds ->
                                resendAvailableAtMillis =
                                    System.currentTimeMillis() +
                                        seconds * 1_000L
                            }
                            errorMessage = error.toUserMessage(
                                "Doğrulama kodu yeniden gönderilemedi."
                            )
                        } finally {
                            isSubmitting = false
                        }
                    }
                },
                enabled = !isSubmitting &&
                    resendSecondsRemaining == 0,
                modifier = Modifier.testTag("otp_resend"),
            ) {
                Text(resendButtonLabel(resendSecondsRemaining))
            }
        }
        if (errorMessage != null) {
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = errorMessage.orEmpty(),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium
            )
        }
        Spacer(modifier = Modifier.height(24.dp))
        Button(
            onClick = {
                val trimmedPhone = phone.trim()
                if (trimmedPhone.isBlank()) {
                    errorMessage = "Telefon numarası zorunludur."
                    return@Button
                }
                if (!isPlausiblePhoneInput(trimmedPhone)) {
                    errorMessage = "Geçerli bir telefon numarası girin."
                    return@Button
                }
                if (challengeId != null && verificationCode.length != 6) {
                    errorMessage = "6 haneli doğrulama kodunu girin."
                    return@Button
                }

                coroutineScope.launch {
                    isSubmitting = true
                    errorMessage = null
                    try {
                        if (challengeId == null) {
                            val response = BackendClient.api.requestOtp(
                                OtpRequest(phone = trimmedPhone)
                            )
                            phone = response.phone
                            challengeId = response.challengeId
                            devCode = response.devCode
                            verificationCode = response.devCode.orEmpty()
                            resendAvailableAtMillis =
                                System.currentTimeMillis() +
                                    response.resendAfterSeconds * 1_000L
                        } else {
                            val response = BackendClient.api.verifyOtp(
                                OtpVerifyRequest(
                                    challengeId = challengeId.orEmpty(),
                                    phone = trimmedPhone,
                                    code = verificationCode
                                )
                            )
                            onRegisterSuccess(response.user, response.accessToken)
                        }
                    } catch (error: Exception) {
                        errorMessage = error.toUserMessage(
                            if (challengeId == null) {
                                "Doğrulama kodu gönderilemedi."
                            } else {
                                "Telefon doğrulanamadı."
                            }
                        )
                    } finally {
                        isSubmitting = false
                    }
                }
            },
            enabled = !isSubmitting,
            modifier = Modifier
                .fillMaxWidth()
                .testTag("registration_submit")
        ) {
            if (isSubmitting) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            } else {
                Text(if (challengeId == null) "Kod Gönder" else "Doğrula ve Devam Et")
            }
        }
        if (challengeId != null) {
            Spacer(modifier = Modifier.height(8.dp))
            TextButton(
                onClick = {
                    challengeId = null
                    verificationCode = ""
                    devCode = null
                    errorMessage = null
                },
                enabled = !isSubmitting
            ) {
                Text("Telefon numarasını değiştir")
            }
        }
    }
}

@Composable
private fun VideoConsentGate(
    userId: String?,
    consentVersion: String,
    privacyPolicyUrl: String,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    var retryAttempt by rememberSaveable { mutableIntStateOf(0) }
    var state by remember {
        mutableStateOf<VideoConsentGateState>(
            VideoConsentGateState.Loading
        )
    }
    var accepted by rememberSaveable { mutableStateOf(false) }
    var isSubmitting by rememberSaveable { mutableStateOf(false) }
    var errorMessage by rememberSaveable {
        mutableStateOf<String?>(null)
    }
    var currentConsentVersion by rememberSaveable(
        consentVersion
    ) {
        mutableStateOf(consentVersion)
    }
    var currentPrivacyPolicyUrl by rememberSaveable(
        privacyPolicyUrl
    ) {
        mutableStateOf(privacyPolicyUrl)
    }

    LaunchedEffect(userId, consentVersion, retryAttempt) {
        state = VideoConsentGateState.Loading
        errorMessage = null
        if (userId.isNullOrBlank() || consentVersion.isBlank()) {
            state = VideoConsentGateState.ConnectionError
            return@LaunchedEffect
        }
        state = try {
            val consent = BackendClient.api
                .getVideoConsent(userId)
                .consent
            currentConsentVersion = consent.version
            currentPrivacyPolicyUrl = consent.policyUrl
                .ifBlank { privacyPolicyUrl }
            if (consent.status == "accepted") {
                VideoConsentGateState.Accepted
            } else {
                VideoConsentGateState.Required
            }
        } catch (_: Exception) {
            VideoConsentGateState.ConnectionError
        }
    }

    when (state) {
        VideoConsentGateState.Loading -> {
            AppAvailabilityScreen(
                title = "Video hazırlığı",
                message = "Video işleme onayı kontrol ediliyor.",
                showProgress = true,
            )
        }

        VideoConsentGateState.Accepted -> content()
        VideoConsentGateState.ConnectionError -> {
            AppAvailabilityScreen(
                title = "Onay bilgisi alınamadı",
                message = (
                    "Bağlantınızı kontrol edip tekrar deneyin."
                ),
                onRetry = { retryAttempt += 1 },
            )
        }

        VideoConsentGateState.Required -> {
            VideoConsentScreen(
                checked = accepted,
                isSubmitting = isSubmitting,
                errorMessage = errorMessage,
                privacyPolicyUrl = currentPrivacyPolicyUrl,
                onCheckedChange = {
                    accepted = it
                    errorMessage = null
                },
                onOpenPrivacy = {
                    runCatching {
                        context.startActivity(
                            Intent(
                                Intent.ACTION_VIEW,
                                Uri.parse(privacyPolicyUrl),
                            )
                        )
                    }.onFailure {
                        errorMessage = (
                            "Gizlilik metni açılamadı."
                        )
                    }
                },
                onAccept = {
                    val workerId = userId
                    if (
                        workerId.isNullOrBlank() ||
                        !accepted ||
                        isSubmitting
                    ) {
                        return@VideoConsentScreen
                    }
                    isSubmitting = true
                    errorMessage = null
                    coroutineScope.launch {
                        try {
                            val consent = BackendClient.api
                                .acceptVideoConsent(
                                    workerId,
                                    VideoConsentRequest(
                                        version =
                                            currentConsentVersion,
                                    ),
                                )
                                .consent
                            if (
                                consent.status != "accepted" ||
                                consent.version !=
                                currentConsentVersion
                            ) {
                                errorMessage = (
                                    "Onay kaydı doğrulanamadı."
                                )
                            } else {
                                state = VideoConsentGateState.Accepted
                            }
                        } catch (error: Exception) {
                            errorMessage = error.toUserMessage(
                                "Video işleme onayı kaydedilemedi.",
                            )
                        } finally {
                            isSubmitting = false
                        }
                    }
                },
            )
        }
    }
}

@Composable
internal fun VideoConsentScreen(
    checked: Boolean,
    isSubmitting: Boolean,
    errorMessage: String?,
    privacyPolicyUrl: String,
    onCheckedChange: (Boolean) -> Unit,
    onOpenPrivacy: () -> Unit,
    onAccept: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = "Video İşleme Onayı",
            style = MaterialTheme.typography.headlineSmall,
        )
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = (
                "Video CV'niz ve konuşma içeriğiniz; aday profili " +
                    "oluşturmak, ad soyad ve beceri çıkarımı yapmak " +
                    "ve uygun işlerle eşleştirmek için işlenecektir."
            ),
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = (
                "Ham video işleme tamamlandıktan sonra sunucudan " +
                    "silinir. Çıkarılan profil ve transkript, hesabınız " +
                    "açık kaldığı sürece saklanır."
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (privacyPolicyUrl.isNotBlank()) {
            TextButton(
                onClick = onOpenPrivacy,
                modifier = Modifier.testTag("video_consent_privacy"),
            ) {
                Text("Gizlilik metnini aç")
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(
                checked = checked,
                onCheckedChange = onCheckedChange,
                enabled = !isSubmitting,
                modifier = Modifier.testTag(
                    "video_consent_checkbox"
                ),
            )
            Text(
                text = (
                    "Video ve ses kaydımın bu amaçlarla " +
                        "işlenmesini onaylıyorum."
                ),
                modifier = Modifier.weight(1f),
            )
        }
        if (errorMessage != null) {
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = errorMessage,
                color = MaterialTheme.colorScheme.error,
            )
        }
        Spacer(modifier = Modifier.height(16.dp))
        Button(
            onClick = onAccept,
            enabled = checked && !isSubmitting,
            modifier = Modifier
                .fillMaxWidth()
                .testTag("video_consent_accept"),
        ) {
            if (isSubmitting) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            } else {
                Text("Onayla ve Kameraya Geç")
            }
        }
    }
}

@Composable
fun OnboardingScreen(onVideoRecorded: (Uri) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    val topics = listOf(
        "Adınız ve soyadınız nedir?",
        "Önceki iş deneyiminizden bahsedin.",
        "Temel becerileriniz nelerdir? (örn. tesisatçılık, kaynak, araç kullanma)",
        "Ne tür bir iş arıyorsunuz?",
        "Müsaitlik durumunuz nedir?"
    )

    val cameraController = remember {
        LifecycleCameraController(context).apply {
            setEnabledUseCases(CameraController.VIDEO_CAPTURE)
            cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
        }
    }

    var recording: Recording? by remember { mutableStateOf(null) }
    var isRecording by remember { mutableStateOf(false) }
    var recordingElapsedSeconds by remember { mutableLongStateOf(0L) }
    var showPreview by remember { mutableStateOf(false) }
    val acceptRecordingResult = remember { AtomicBoolean(true) }
    DisposableEffect(cameraController, lifecycleOwner) {
        acceptRecordingResult.set(true)
        cameraController.bindToLifecycle(lifecycleOwner)
        onDispose {
            acceptRecordingResult.set(false)
            recording?.stop()
            recording = null
            cameraController.unbind()
        }
    }

    val permissions = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
    var hasPermissions by remember {
        mutableStateOf(permissions.all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        })
    }
    val launcher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        hasPermissions = result.values.all { it }
        if (hasPermissions) showPreview = true
    }

    Scaffold(
        bottomBar = {
            Column(
                modifier = Modifier
                    .navigationBarsPadding()
                    .padding(horizontal = 16.dp, vertical = 8.dp)
            ) {
                if (showPreview && hasPermissions) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(220.dp)
                            .clip(RoundedCornerShape(12.dp))
                    ) {
                        AndroidView(
                            factory = { ctx ->
                                androidx.camera.view.PreviewView(ctx).apply {
                                    this.controller = cameraController
                                }
                            },
                            modifier = Modifier.fillMaxSize()
                        )
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                }
                Button(
                    onClick = {
                        when {
                            !showPreview -> {
                                if (hasPermissions) showPreview = true
                                else launcher.launch(permissions)
                            }
                            !isRecording -> {
                                val file = File(context.cacheDir, "cv_video_${System.currentTimeMillis()}.mp4")
                                val outputOptions = createVideoOutputOptions(file)
                                recordingElapsedSeconds = 0L
                                isRecording = true
                                recording = cameraController.startRecording(
                                    outputOptions,
                                    AudioConfig.create(true),
                                    ContextCompat.getMainExecutor(context)
                                ) { event ->
                                    when (event) {
                                        is VideoRecordEvent.Status -> {
                                            recordingElapsedSeconds =
                                                event.recordingStats.recordedDurationNanos /
                                                    1_000_000_000L
                                        }
                                        is VideoRecordEvent.Finalize -> {
                                            isRecording = false
                                            recording = null
                                            if (
                                                shouldAcceptRecordingFinalize(
                                                    event.error,
                                                    acceptRecordingResult.get(),
                                                )
                                            ) {
                                                onVideoRecorded(Uri.fromFile(file))
                                            } else {
                                                deleteCapturedVideo(file)
                                                if (
                                                    shouldLogRecordingError(
                                                        event.error
                                                    )
                                                ) {
                                                    Log.e(
                                                        "CameraX",
                                                        "Video capture failed: ${event.error}",
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            else -> {
                                recording?.stop()
                                recording = null
                                isRecording = false
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = if (isRecording)
                        ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                    else
                        ButtonDefaults.buttonColors()
                ) {
                    Text(when {
                        !showPreview -> "Video Çekmeye Başla"
                        !isRecording -> "Kaydı Başlat"
                        else -> "Kaydı Durdur · ${
                            formatRecordingDuration(recordingElapsedSeconds)
                        } / 01:30"
                    })
                }
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp)
        ) {
            Spacer(modifier = Modifier.height(48.dp))
            Text(text = "Hoş Geldiniz! Video CV'nizi Oluşturalım", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(16.dp))
            Text(text = "Lütfen aşağıdaki konuları yanıtlayan kısa bir video kaydedin:")
            Spacer(modifier = Modifier.height(16.dp))
            LazyColumn {
                items(topics) { topic ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
                    ) {
                        Text(text = topic, modifier = Modifier.padding(16.dp))
                    }
                }
            }
        }
    }
}

@Composable
fun VideoRecordScreen(onVideoRecorded: (Uri) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    val cameraController = remember {
        LifecycleCameraController(context).apply {
            setEnabledUseCases(CameraController.VIDEO_CAPTURE)
            cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
        }
    }

    var recording: Recording? by remember { mutableStateOf(null) }
    var isRecording by remember { mutableStateOf(false) }
    var recordingElapsedSeconds by remember { mutableLongStateOf(0L) }
    val acceptRecordingResult = remember { AtomicBoolean(true) }
    DisposableEffect(cameraController, lifecycleOwner) {
        acceptRecordingResult.set(true)
        cameraController.bindToLifecycle(lifecycleOwner)
        onDispose {
            acceptRecordingResult.set(false)
            recording?.stop()
            recording = null
            cameraController.unbind()
        }
    }

    val permissions = arrayOf(
        Manifest.permission.CAMERA,
        Manifest.permission.RECORD_AUDIO
    )

    var hasPermissions by remember {
        mutableStateOf(
            permissions.all {
                ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
            }
        )
    }

    val launcher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        hasPermissions = result.values.all { it }
    }

    LaunchedEffect(Unit) {
        if (!hasPermissions) {
            launcher.launch(permissions)
        }
    }

    if (hasPermissions) {
        Box(modifier = Modifier.fillMaxSize()) {
            AndroidView(
                factory = { ctx ->
                    androidx.camera.view.PreviewView(ctx).apply {
                        this.controller = cameraController
                    }
                },
                modifier = Modifier.fillMaxSize()
            )

            Column(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 48.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                if (isRecording) {
                    Text(
                        text = "${
                            formatRecordingDuration(recordingElapsedSeconds)
                        } / 01:30",
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(
                        onClick = {
                            recording?.stop()
                            recording = null
                            isRecording = false
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                    ) {
                        Text("Kaydı Durdur")
                    }
                } else {
                    Button(onClick = {
                        val file = File(context.cacheDir, "cv_video_${System.currentTimeMillis()}.mp4")
                        val outputOptions = createVideoOutputOptions(file)

                        recordingElapsedSeconds = 0L
                        isRecording = true
                        recording = cameraController.startRecording(
                            outputOptions,
                            AudioConfig.create(true),
                            ContextCompat.getMainExecutor(context)
                        ) { event ->
                            when (event) {
                                is VideoRecordEvent.Status -> {
                                    recordingElapsedSeconds =
                                        event.recordingStats.recordedDurationNanos /
                                            1_000_000_000L
                                }
                                is VideoRecordEvent.Finalize -> {
                                    isRecording = false
                                    recording = null
                                    if (
                                        shouldAcceptRecordingFinalize(
                                            event.error,
                                            acceptRecordingResult.get(),
                                        )
                                    ) {
                                        onVideoRecorded(Uri.fromFile(file))
                                    } else {
                                        deleteCapturedVideo(file)
                                        if (
                                            shouldLogRecordingError(
                                                event.error
                                            )
                                        ) {
                                            Log.e(
                                                "CameraX",
                                                "Video capture failed: ${event.error}",
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }) {
                        Text("Kaydı Başlat")
                    }
                }
            }
        }
    } else {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Kamera ve Ses izinleri gereklidir")
                Spacer(modifier = Modifier.height(16.dp))
                Button(onClick = { launcher.launch(permissions) }) {
                    Text("İzin Ver")
                }
            }
        }
    }
}

@Composable
fun UploadScreen(userId: String?, videoUri: String?, onUploadComplete: () -> Unit) {
    var isUploading by remember { mutableStateOf(true) }
    var isUploaded by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var uploadAttempt by rememberSaveable(
        userId,
        videoUri,
    ) { mutableIntStateOf(0) }
    val idempotencyKey = rememberSaveable(userId, videoUri) {
        BackendClient.newIdempotencyKey()
    }

    LaunchedEffect(userId, videoUri, uploadAttempt) {
        if (userId.isNullOrBlank() || videoUri.isNullOrBlank()) {
            isUploading = false
            errorMessage = "Kullanıcı veya video bilgisi bulunamadı."
            return@LaunchedEffect
        }

        isUploading = true
        isUploaded = false
        errorMessage = null
        try {
            val videoFile = File(
                Uri.parse(Uri.decode(videoUri)).path.orEmpty()
            )
            val uploadSha256 = withContext(Dispatchers.IO) {
                sha256Hex(videoFile)
            }
            val videoPart = createVideoPart(videoFile)
            BackendClient.api.uploadVideo(
                userId = userId,
                video = videoPart,
                idempotencyKey = idempotencyKey,
                uploadSha256 = uploadSha256,
            )
            withContext(Dispatchers.IO) {
                if (!deleteCapturedVideo(videoFile)) {
                    Log.w(
                        "VideoUpload",
                        "Uploaded local video could not be deleted",
                    )
                }
            }
            isUploaded = true
        } catch (error: Exception) {
            errorMessage = error.toUserMessage("Video yüklenemedi.")
        } finally {
            isUploading = false
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        if (isUploading) {
            Text(text = "Video CV'niz yükleniyor...", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(16.dp))
            CircularProgressIndicator()
        } else if (isUploaded) {
            Text(text = "Yükleme Tamamlandı!", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(16.dp))
            Text(text = "Yapay zekamız profilinizi oluşturmak için videonuzu işliyor.")
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onUploadComplete) {
                Text("Panele Git")
            }
        } else {
            Text(text = "Yükleme Başarısız", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = errorMessage ?: "Beklenmeyen bir hata oluştu.",
                color = MaterialTheme.colorScheme.error
            )
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = { uploadAttempt += 1 }) {
                Text("Tekrar Dene")
            }
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedButton(onClick = onUploadComplete) {
                Text("Panele Git")
            }
        }
    }
}

@Composable
fun DashboardScreen(
    userId: String?,
    onUpdateVideo: () -> Unit,
    onAccountDeleted: () -> Unit,
    onResetSession: () -> Unit,
) {
    var dashboard by remember { mutableStateOf<DashboardResponse?>(null) }
    var isLoading by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var workerQuestion by remember { mutableStateOf("") }
    var workerAnswer by remember { mutableStateOf<String?>(null) }
    var isAskingQuestion by remember { mutableStateOf(false) }
    var actionMessage by remember { mutableStateOf<String?>(null) }
    var jobActionMessage by remember { mutableStateOf<String?>(null) }
    var profileNameInput by rememberSaveable(userId) {
        mutableStateOf("")
    }
    var isEditingProfileName by rememberSaveable(userId) {
        mutableStateOf(false)
    }
    var isSavingProfileName by remember {
        mutableStateOf(false)
    }
    var profileReviewMessage by remember {
        mutableStateOf<String?>(null)
    }
    var profileReviewError by remember {
        mutableStateOf<String?>(null)
    }
    var applyingJobId by remember { mutableStateOf<String?>(null) }
    var withdrawingJobApplicationId by remember {
        mutableStateOf<String?>(null)
    }
    var activeWorkerActionKey by remember {
        mutableStateOf<String?>(null)
    }
    var isDeletingAccount by remember { mutableStateOf(false) }
    var isExportingAccountData by remember {
        mutableStateOf(false)
    }
    var accountActionError by remember {
        mutableStateOf<String?>(null)
    }
    var isWithdrawingVideoConsent by remember {
        mutableStateOf(false)
    }
    var consentActionMessage by remember {
        mutableStateOf<String?>(null)
    }
    var consentActionError by remember {
        mutableStateOf<String?>(null)
    }
    var refreshTick by remember { mutableIntStateOf(0) }
    val coroutineScope = rememberCoroutineScope()
    val lifecycleOwner = LocalLifecycleOwner.current
    val context = LocalContext.current
    var notificationsAllowed by remember {
        mutableStateOf(hasNotificationPermission(context))
    }
    val notificationPermissionLauncher =
        rememberLauncherForActivityResult(
            ActivityResultContracts.RequestPermission()
        ) { granted ->
            notificationsAllowed = granted
        }
    DisposableEffect(lifecycleOwner, context) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                notificationsAllowed =
                    hasNotificationPermission(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }
    LaunchedEffect(
        dashboard?.user?.name,
        dashboard?.user?.profileReviewStatus,
        dashboard?.candidateProfile?.name,
    ) {
        val currentName = dashboard?.user?.name
            ?.takeIf { it.isNotBlank() }
            ?: dashboard?.candidateProfile?.name.orEmpty()
        if (!isEditingProfileName || profileNameInput.isBlank()) {
            profileNameInput = currentName
        }
        if (
            dashboard?.candidateProfile != null &&
            dashboard?.user?.profileReviewStatus != "confirmed"
        ) {
            isEditingProfileName = true
        }
    }

    LaunchedEffect(userId, refreshTick, lifecycleOwner) {
        if (userId.isNullOrBlank()) {
            errorMessage = "Kullanıcı bilgisi bulunamadı."
            return@LaunchedEffect
        }

        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            isLoading = dashboard == null
            errorMessage = null
            try {
                do {
                    val response = BackendClient.api.getDashboard(userId)
                    dashboard = response
                    withContext(Dispatchers.IO) {
                        DashboardNotificationStore(context).save(
                            response.toNotificationSnapshot()
                        )
                    }
                    isLoading = false
                    val refreshDelay = dashboardRefreshDelay(response)
                    if (refreshDelay != null) delay(refreshDelay)
                } while (refreshDelay != null)
            } catch (error: Exception) {
                errorMessage = error.toUserMessage("Panel bilgileri alınamadı.")
            } finally {
                isLoading = false
            }
        }
    }

    Scaffold(
        floatingActionButton = {
            FloatingActionButton(onClick = onUpdateVideo) {
                Icon(Icons.Default.Create, contentDescription = "Videoyu Güncelle")
            }
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .verticalScroll(rememberScrollState())
                .padding(16.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(text = "Çalışan Paneli", style = MaterialTheme.typography.headlineMedium)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(
                        onClick = { refreshTick += 1 },
                        enabled = !isLoading
                    ) {
                        Icon(
                            Icons.Default.Refresh,
                            contentDescription = "Paneli Yenile"
                        )
                    }
                    TextButton(onClick = onResetSession) {
                        Text("Çıkış")
                    }
                }
            }
            if (
                Build.VERSION.SDK_INT >=
                Build.VERSION_CODES.TIRAMISU &&
                !notificationsAllowed
            ) {
                NotificationPermissionAction(
                    onRequest = {
                        notificationPermissionLauncher.launch(
                            Manifest.permission.POST_NOTIFICATIONS
                        )
                    }
                )
            }
            Spacer(modifier = Modifier.height(24.dp))

            when {
                isLoading -> {
                    Box(
                        modifier = Modifier.fillMaxWidth().height(160.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator()
                    }
                }
                errorMessage != null -> {
                    Text(
                        text = errorMessage.orEmpty(),
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
                else -> {
                    val data = dashboard
                    DashboardCard(
                        title = "Profil Durumu",
                        status = data?.user?.profileStatus?.toStatusLabel() ?: "Bekleniyor",
                        icon = Icons.Default.Person
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    DashboardCard(
                        title = "Video CV",
                        status = data?.latestVideo?.status?.toStatusLabel() ?: "Video yüklenmedi",
                        icon = Icons.Default.Create
                    )

                    data?.candidateProfile?.let { profile ->
                        val profileUser = data.user
                        Spacer(modifier = Modifier.height(16.dp))
                        ProfileReviewCard(
                            user = profileUser,
                            profile = profile,
                            nameInput = profileNameInput,
                            isEditing = isEditingProfileName,
                            isSaving = isSavingProfileName,
                            successMessage = profileReviewMessage,
                            errorMessage = profileReviewError,
                            onNameChange = {
                                profileNameInput = it.take(100)
                                profileReviewMessage = null
                                profileReviewError = null
                            },
                            onEdit = {
                                isEditingProfileName = true
                                profileReviewMessage = null
                                profileReviewError = null
                            },
                            onCancel = {
                                profileNameInput =
                                    profileUser.name.ifBlank {
                                        profile.name.orEmpty()
                                    }
                                isEditingProfileName = false
                                profileReviewError = null
                            },
                            onSave = {
                                val currentUserId = userId
                                val name = profileNameInput.trim()
                                if (
                                    currentUserId.isNullOrBlank() ||
                                    name.length < 2 ||
                                    isSavingProfileName
                                ) {
                                    return@ProfileReviewCard
                                }
                                coroutineScope.launch {
                                    isSavingProfileName = true
                                    profileReviewMessage = null
                                    profileReviewError = null
                                    try {
                                        val response =
                                            BackendClient.api.reviewProfile(
                                                currentUserId,
                                                ProfileReviewRequest(name),
                                            )
                                        dashboard = dashboard?.copy(
                                            user = response.user,
                                            candidateProfile =
                                                response.candidateProfile,
                                        )
                                        profileNameInput =
                                            response.user.name
                                        isEditingProfileName = false
                                        profileReviewMessage =
                                            "Ad soyad kaydedildi."
                                    } catch (error: Exception) {
                                        profileReviewError =
                                            error.toUserMessage(
                                                "Ad soyad kaydedilemedi."
                                            )
                                    } finally {
                                        isSavingProfileName = false
                                    }
                                }
                            },
                        )
                    }

                    Spacer(modifier = Modifier.height(32.dp))
                    Text(text = "Tavsiye Edilen İşler", style = MaterialTheme.typography.titleLarge)
                    Text(
                        text = if (data?.recommendedJobs.isNullOrEmpty()) {
                            "Video işleme tamamlandığında uygun işler burada görüntülenecek"
                        } else {
                            "Profilinize uygun işler"
                        },
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    Spacer(modifier = Modifier.height(16.dp))
                    if (data?.recommendedJobs.isNullOrEmpty()) {
                        repeat(2) {
                            Card(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                            ) {
                                Column(modifier = Modifier.padding(16.dp)) {
                                    Box(
                                        modifier = Modifier.fillMaxWidth().height(100.dp).padding(bottom = 8.dp),
                                        contentAlignment = Alignment.Center
                                    ) {
                                        Text(
                                            "İş eşleşmeleri hazırlanıyor...",
                                            color = MaterialTheme.colorScheme.outline
                                        )
                                    }
                                }
                            }
                        }
                    } else {
                        data?.recommendedJobs?.forEach { job ->
                            JobRecommendationCard(
                                job = job,
                                isApplying = applyingJobId == job.id,
                                onApply = {
                                    val currentUserId = userId
                                    val jobId = job.id
                                    if (currentUserId.isNullOrBlank() || jobId.isNullOrBlank()) {
                                        return@JobRecommendationCard
                                    }
                                    coroutineScope.launch {
                                        applyingJobId = jobId
                                        jobActionMessage = null
                                        try {
                                            BackendClient.api.applyToJob(
                                                currentUserId,
                                                JobApplicationRequest(
                                                    jobRecommendationId = jobId
                                                ),
                                                BackendClient.newIdempotencyKey()
                                            )
                                            jobActionMessage = "Başvuru alındı."
                                            refreshTick += 1
                                        } catch (error: Exception) {
                                            jobActionMessage = error.toUserMessage("Başvuru gönderilemedi.")
                                        } finally {
                                            applyingJobId = null
                                        }
                                    }
                                }
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                    }
                    if (!jobActionMessage.isNullOrBlank()) {
                        Text(
                            text = jobActionMessage.orEmpty(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                    if (!data?.jobApplications.isNullOrEmpty()) {
                        Spacer(modifier = Modifier.height(24.dp))
                        JobApplicationsSection(
                            applications =
                                data?.jobApplications.orEmpty(),
                            withdrawingApplicationId =
                                withdrawingJobApplicationId,
                            onWithdraw = { applicationId ->
                                val currentUserId =
                                    userId ?: return@JobApplicationsSection
                                if (
                                    withdrawingJobApplicationId != null
                                ) {
                                    return@JobApplicationsSection
                                }
                                coroutineScope.launch {
                                    withdrawingJobApplicationId =
                                        applicationId
                                    jobActionMessage = null
                                    try {
                                        BackendClient.api
                                            .withdrawJobApplication(
                                                currentUserId,
                                                applicationId,
                                                BackendClient
                                                    .newIdempotencyKey(),
                                            )
                                        jobActionMessage =
                                            "Başvuru geri çekildi."
                                        refreshTick += 1
                                    } catch (error: Exception) {
                                        jobActionMessage =
                                            error.toUserMessage(
                                                "Başvuru geri çekilemedi."
                                            )
                                    } finally {
                                        withdrawingJobApplicationId =
                                            null
                                    }
                                }
                            },
                        )
                    }

                    data?.workerHub?.let { hub ->
                        Spacer(modifier = Modifier.height(24.dp))
                        WorkerHubSection(
                            hub = hub,
                            question = workerQuestion,
                            answer = workerAnswer,
                            isAsking = isAskingQuestion,
                            onQuestionChange = { workerQuestion = it },
                            onAskQuestion = {
                                val currentUserId = userId
                                val question = workerQuestion.trim()
                                if (
                                    currentUserId.isNullOrBlank() ||
                                    question.isBlank() ||
                                    isAskingQuestion
                                ) {
                                    return@WorkerHubSection
                                }
                                coroutineScope.launch {
                                    isAskingQuestion = true
                                    workerAnswer = null
                                    try {
                                        val response = BackendClient.api.askQuestion(
                                            currentUserId,
                                            AskQuestionRequest(question),
                                            BackendClient.newIdempotencyKey()
                                        )
                                        workerAnswer = response.answer.answer
                                        workerQuestion = ""
                                        refreshTick += 1
                                    } catch (error: Exception) {
                                        workerAnswer = error.toUserMessage("Cevap alınamadı.")
                                    } finally {
                                        isAskingQuestion = false
                                    }
                                }
                            },
                            actionMessage = actionMessage,
                            activeActionKey = activeWorkerActionKey,
                            onCompleteAssessment = { assessmentId, answers ->
                                val currentUserId = userId ?: return@WorkerHubSection
                                val workerActionKey =
                                    assessmentActionKey(assessmentId)
                                if (activeWorkerActionKey != null) {
                                    return@WorkerHubSection
                                }
                                activeWorkerActionKey = workerActionKey
                                coroutineScope.launch {
                                    actionMessage = null
                                    try {
                                        BackendClient.api.completeAssessment(
                                            currentUserId,
                                            assessmentId,
                                            CompleteAssessmentRequest(
                                                answers = answers
                                            ),
                                            BackendClient.newIdempotencyKey()
                                        )
                                        actionMessage = "Değerlendirme tamamlandı."
                                        refreshTick += 1
                                    } catch (error: Exception) {
                                        actionMessage = error.toUserMessage("Değerlendirme tamamlanamadı.")
                                    } finally {
                                        if (
                                            activeWorkerActionKey ==
                                            workerActionKey
                                        ) {
                                            activeWorkerActionKey = null
                                        }
                                    }
                                }
                            },
                            onSaveTrainingProgress = {
                                    trainingId,
                                    moduleIds,
                                ->
                                val currentUserId = userId ?: return@WorkerHubSection
                                val workerActionKey =
                                    trainingActionKey(trainingId)
                                if (activeWorkerActionKey != null) {
                                    return@WorkerHubSection
                                }
                                activeWorkerActionKey = workerActionKey
                                coroutineScope.launch {
                                    actionMessage = null
                                    try {
                                        val response =
                                            BackendClient.api
                                                .saveTrainingProgress(
                                            currentUserId,
                                            trainingId,
                                            UpdateTrainingProgressRequest(
                                                completedModules = moduleIds
                                            ),
                                            BackendClient.newIdempotencyKey()
                                        )
                                        actionMessage =
                                            if (
                                                response.training.status ==
                                                "completed"
                                            ) {
                                                "Eğitim tamamlandı."
                                            } else {
                                                "Eğitim ilerlemesi kaydedildi."
                                            }
                                        refreshTick += 1
                                    } catch (error: Exception) {
                                        actionMessage = error.toUserMessage("Eğitim tamamlanamadı.")
                                    } finally {
                                        if (
                                            activeWorkerActionKey ==
                                            workerActionKey
                                        ) {
                                            activeWorkerActionKey = null
                                        }
                                    }
                                }
                            },
                            onRequestShuttle = { routeId, pickupNote ->
                                val currentUserId = userId ?: return@WorkerHubSection
                                val workerActionKey =
                                    shuttleActionKey(routeId)
                                if (activeWorkerActionKey != null) {
                                    return@WorkerHubSection
                                }
                                activeWorkerActionKey = workerActionKey
                                coroutineScope.launch {
                                    actionMessage = null
                                    try {
                                        BackendClient.api.requestShuttle(
                                            currentUserId,
                                            ShuttleRequestRequest(
                                                routeId = routeId,
                                                pickupNote = pickupNote
                                            ),
                                            BackendClient.newIdempotencyKey()
                                        )
                                        actionMessage = "Servis isteği alındı."
                                        refreshTick += 1
                                    } catch (error: Exception) {
                                        actionMessage = error.toUserMessage("Servis isteği alınamadı.")
                                    } finally {
                                        if (
                                            activeWorkerActionKey ==
                                            workerActionKey
                                        ) {
                                            activeWorkerActionKey = null
                                        }
                                    }
                                }
                            },
                            onCancelShuttle = { requestId ->
                                val currentUserId =
                                    userId ?: return@WorkerHubSection
                                val workerActionKey =
                                    shuttleCancelActionKey(requestId)
                                if (activeWorkerActionKey != null) {
                                    return@WorkerHubSection
                                }
                                activeWorkerActionKey = workerActionKey
                                coroutineScope.launch {
                                    actionMessage = null
                                    try {
                                        BackendClient.api.cancelShuttle(
                                            currentUserId,
                                            requestId,
                                            BackendClient
                                                .newIdempotencyKey(),
                                        )
                                        actionMessage =
                                            "Servis talebi iptal edildi."
                                        refreshTick += 1
                                    } catch (error: Exception) {
                                        actionMessage =
                                            error.toUserMessage(
                                                "Servis talebi iptal edilemedi."
                                            )
                                    } finally {
                                        if (
                                            activeWorkerActionKey ==
                                            workerActionKey
                                        ) {
                                            activeWorkerActionKey = null
                                        }
                                    }
                                }
                            }
                        )
                        val recentQuestions = data?.recentQuestions.orEmpty()
                        if (recentQuestions.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(16.dp))
                            QuestionHistorySection(
                                questions = recentQuestions,
                                pendingQuestionCount =
                                    data?.pendingQuestionCount ?: 0
                            )
                        }
                    }
                }
            }
            HorizontalDivider(modifier = Modifier.padding(top = 32.dp))
            VideoConsentManagementSection(
                consentStatus = dashboard?.videoConsent?.status,
                isWithdrawing = isWithdrawingVideoConsent,
                successMessage = consentActionMessage,
                errorMessage = consentActionError,
                onWithdraw = {
                    val currentUserId = userId
                    if (
                        currentUserId.isNullOrBlank() ||
                        isWithdrawingVideoConsent
                    ) {
                        return@VideoConsentManagementSection
                    }
                    coroutineScope.launch {
                        isWithdrawingVideoConsent = true
                        consentActionMessage = null
                        consentActionError = null
                        try {
                            val response = BackendClient.api
                                .withdrawVideoConsent(
                                    currentUserId
                                )
                            dashboard = dashboard?.copy(
                                videoConsent = response.consent,
                            )
                            consentActionMessage = (
                                "Video işleme onayı geri çekildi."
                            )
                        } catch (error: Exception) {
                            consentActionError = error.toUserMessage(
                                "Video işleme onayı geri çekilemedi."
                            )
                        } finally {
                            isWithdrawingVideoConsent = false
                        }
                    }
                },
            )
            AccountDeletionSection(
                isDeleting = isDeletingAccount,
                isExporting = isExportingAccountData,
                errorMessage = accountActionError,
                onExport = {
                    val currentUserId = userId
                    if (
                        currentUserId.isNullOrBlank() ||
                        isExportingAccountData
                    ) {
                        return@AccountDeletionSection
                    }
                    coroutineScope.launch {
                        isExportingAccountData = true
                        accountActionError = null
                        try {
                            val response =
                                BackendClient.api.exportAccountData(
                                    currentUserId
                                )
                            val exportFile =
                                withContext(Dispatchers.IO) {
                                    response.use {
                                        writeWorkerDataExport(
                                            context.cacheDir,
                                            it.byteStream(),
                                        )
                                    }
                                }
                            shareWorkerDataExport(context, exportFile)
                        } catch (error: Exception) {
                            accountActionError = error.toUserMessage(
                                "Veriler dışa aktarılamadı."
                            )
                        } finally {
                            isExportingAccountData = false
                        }
                    }
                },
                onConfirm = {
                    val currentUserId = userId
                    if (
                        currentUserId.isNullOrBlank() ||
                        isDeletingAccount
                    ) {
                        return@AccountDeletionSection
                    }
                    coroutineScope.launch {
                        isDeletingAccount = true
                        accountActionError = null
                        try {
                            BackendClient.api.deleteAccount(
                                currentUserId
                            )
                            onAccountDeleted()
                        } catch (error: Exception) {
                            accountActionError = error.toUserMessage(
                                "Hesap silinemedi."
                            )
                        } finally {
                            isDeletingAccount = false
                        }
                    }
                },
            )
            Spacer(modifier = Modifier.height(96.dp))
        }
    }
}

@Composable
internal fun NotificationPermissionAction(
    onRequest: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Default.Notifications,
                contentDescription = null,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                "İşveren güncellemeleri",
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        TextButton(
            onClick = onRequest,
            modifier = Modifier.testTag("enable_notifications"),
        ) {
            Text("Bildirimleri Aç")
        }
    }
}

@Composable
internal fun ProfileReviewCard(
    user: UserDto,
    profile: CandidateProfileDto,
    nameInput: String,
    isEditing: Boolean,
    isSaving: Boolean,
    successMessage: String?,
    errorMessage: String?,
    onNameChange: (String) -> Unit,
    onEdit: () -> Unit,
    onCancel: () -> Unit,
    onSave: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "Aday Profili",
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    text = if (
                        user.profileReviewStatus == "confirmed"
                    ) {
                        "Ad doğrulandı"
                    } else {
                        "Ad onayı bekliyor"
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = if (
                        user.profileReviewStatus == "confirmed"
                    ) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.error
                    },
                )
            }
            Spacer(modifier = Modifier.height(10.dp))
            if (isEditing) {
                OutlinedTextField(
                    value = nameInput,
                    onValueChange = onNameChange,
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("profile_name_input"),
                    label = { Text("Ad Soyad") },
                    singleLine = true,
                    enabled = !isSaving,
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    if (user.profileReviewStatus == "confirmed") {
                        TextButton(
                            onClick = onCancel,
                            enabled = !isSaving,
                        ) {
                            Text("Vazgeç")
                        }
                    }
                    Button(
                        onClick = onSave,
                        enabled = (
                            nameInput.trim().length >= 2 &&
                                !isSaving
                            ),
                        modifier = Modifier.testTag(
                            "profile_name_save"
                        ),
                    ) {
                        if (isSaving) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Text("Kaydet")
                        }
                    }
                }
            } else {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement =
                        Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = user.name.ifBlank {
                            profile.name.orEmpty()
                        },
                        style = MaterialTheme.typography.titleLarge,
                    )
                    TextButton(onClick = onEdit) {
                        Icon(
                            Icons.Default.Create,
                            contentDescription = null,
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Düzenle")
                    }
                }
            }
            successMessage?.let {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            errorMessage?.let {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (!profile.summary.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(10.dp))
                Text(
                    text = profile.summary,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            if (profile.skills.isNotEmpty()) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = profile.skills.joinToString(" • "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
internal fun VideoConsentManagementSection(
    consentStatus: String?,
    isWithdrawing: Boolean,
    successMessage: String?,
    errorMessage: String?,
    onWithdraw: () -> Unit,
) {
    var showConfirmation by remember { mutableStateOf(false) }
    val hasActiveConsent = consentStatus == "accepted"

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 20.dp),
    ) {
        Text(
            text = "Video İşleme Onayı",
            style = MaterialTheme.typography.titleMedium,
        )
        Text(
            text = if (hasActiveConsent) {
                "Video ve konuşma içeriğinizin profil oluşturmak " +
                    "için işlenmesine onay verdiniz."
            } else {
                "Gelecekte video eklemek için yeniden onay vermeniz " +
                    "gerekecek."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (hasActiveConsent) {
            TextButton(
                onClick = { showConfirmation = true },
                enabled = !isWithdrawing,
                modifier = Modifier.testTag(
                    "video_consent_withdraw_open"
                ),
                colors = ButtonDefaults.textButtonColors(
                    contentColor = MaterialTheme.colorScheme.error,
                ),
            ) {
                Text(
                    if (isWithdrawing) {
                        "Onay geri çekiliyor..."
                    } else {
                        "Onayı Geri Çek"
                    }
                )
            }
        }
        successMessage?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        errorMessage?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }

    if (showConfirmation) {
        AlertDialog(
            onDismissRequest = {
                if (!isWithdrawing) showConfirmation = false
            },
            title = { Text("Video işleme onayını geri çek") },
            text = {
                Text(
                    "Bu işlem gelecekteki video yüklemelerini " +
                        "durdurur. Mevcut profil ve transkript " +
                        "silinmez; bunları silmek için hesabınızı " +
                        "silmeniz gerekir."
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showConfirmation = false
                        onWithdraw()
                    },
                    enabled = !isWithdrawing,
                    modifier = Modifier.testTag(
                        "video_consent_withdraw_confirm"
                    ),
                    colors = ButtonDefaults.buttonColors(
                        containerColor =
                            MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text("Onayı Geri Çek")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { showConfirmation = false },
                    enabled = !isWithdrawing,
                ) {
                    Text("Vazgeç")
                }
            },
        )
    }
}

@Composable
internal fun AccountDeletionSection(
    isDeleting: Boolean,
    isExporting: Boolean,
    errorMessage: String?,
    onExport: () -> Unit,
    onConfirm: () -> Unit,
) {
    var showConfirmation by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 20.dp),
    ) {
        Text(
            text = "Hesap",
            style = MaterialTheme.typography.titleMedium,
        )
        Text(
            text = "Hesabınızı ve kişisel verilerinizi kalıcı olarak silin.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedButton(
            onClick = onExport,
            enabled = !isExporting && !isDeleting,
            modifier = Modifier
                .padding(top = 12.dp)
                .testTag("account_data_export"),
        ) {
            Icon(
                Icons.Default.Share,
                contentDescription = null,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                if (isExporting) {
                    "Veriler hazırlanıyor..."
                } else {
                    "Verilerimi Dışa Aktar"
                }
            )
        }
        TextButton(
            onClick = { showConfirmation = true },
            enabled = !isDeleting,
            modifier = Modifier.testTag("account_delete_open"),
            colors = ButtonDefaults.textButtonColors(
                contentColor = MaterialTheme.colorScheme.error,
            ),
        ) {
            Icon(
                Icons.Default.Delete,
                contentDescription = null,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                if (isDeleting) {
                    "Hesap siliniyor..."
                } else {
                    "Hesabımı Sil"
                }
            )
        }
        if (!errorMessage.isNullOrBlank()) {
            Text(
                text = errorMessage,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }

    if (showConfirmation) {
        AlertDialog(
            onDismissRequest = {
                if (!isDeleting) showConfirmation = false
            },
            title = { Text("Hesabı kalıcı olarak sil") },
            text = {
                Text(
                    "Video CV'niz, profiliniz, destek talepleriniz ve " +
                        "kişisel bilgileriniz kalıcı olarak silinir. İş " +
                        "başvuruları kimliksizleştirilmiş operasyon kaydı " +
                        "olarak tutulur. Bu işlem geri alınamaz."
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        showConfirmation = false
                        onConfirm()
                    },
                    enabled = !isDeleting,
                    modifier = Modifier.testTag(
                        "account_delete_confirm"
                    ),
                    colors = ButtonDefaults.textButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text("Kalıcı Olarak Sil")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { showConfirmation = false },
                    enabled = !isDeleting,
                ) {
                    Text("Vazgeç")
                }
            },
        )
    }
}

private fun shareWorkerDataExport(
    context: Context,
    exportFile: File,
) {
    val uri = FileProvider.getUriForFile(
        context,
        "${context.packageName}.fileprovider",
        exportFile,
    )
    val shareIntent = Intent(Intent.ACTION_SEND).apply {
        type = "application/json"
        putExtra(Intent.EXTRA_STREAM, uri)
        clipData = ClipData.newRawUri("Çalışan veri dışa aktarımı", uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(
        Intent.createChooser(
            shareIntent,
            "Verilerimi paylaş",
        )
    )
}

private fun hasNotificationPermission(context: Context): Boolean {
    return Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
}

@Composable
fun WorkerHubSection(
    hub: WorkerHubDto,
    question: String,
    answer: String?,
    isAsking: Boolean,
    onQuestionChange: (String) -> Unit,
    onAskQuestion: () -> Unit,
    actionMessage: String?,
    activeActionKey: String?,
    onCompleteAssessment: (String, List<AssessmentAnswerRequest>) -> Unit,
    onSaveTrainingProgress: (String, List<String>) -> Unit,
    onRequestShuttle: (String, String) -> Unit,
    onCancelShuttle: (String) -> Unit,
) {
    var assessmentAnswers by remember(hub.employerKey) { mutableStateOf<Map<String, String>>(emptyMap()) }
    var reviewedTrainingModules by remember(hub.employerKey) {
        mutableStateOf<Set<String>>(emptySet())
    }
    var shuttleNote by remember(hub.employerKey, hub.shuttle?.pickupNote) {
        mutableStateOf(hub.shuttle?.pickupNote.orEmpty())
    }
    var pendingShuttleCancellationId by remember {
        mutableStateOf<String?>(null)
    }
    LaunchedEffect(hub.trainings) {
        reviewedTrainingModules = hub.trainings
            .flatMap { training ->
                val trainingId = training.id
                    ?: return@flatMap emptyList()
                training.completedModules.map { moduleId ->
                    trainingModuleKey(trainingId, moduleId)
                }
            }
            .toSet()
    }

    Text(text = "Çalışan Destek", style = MaterialTheme.typography.titleLarge)
    Spacer(modifier = Modifier.height(12.dp))

    hub.assessments.forEach { item ->
        val assessmentId = item.id
        val hasCompletedResult = item.status == "completed"
        val isPassed = hasCompletedResult &&
            item.passed != false
        val canRetry = hasCompletedResult &&
            item.passed == false
        val actionKey = assessmentId?.let(::assessmentActionKey)
        val isSubmitting = actionKey != null &&
            activeActionKey == actionKey
        val requiredQuestionsAnswered = item.questions.isEmpty() || item.questions.all { assessmentQuestion ->
            val questionId = assessmentQuestion.id
            !assessmentId.isNullOrBlank() &&
                !questionId.isNullOrBlank() &&
                assessmentAnswers[assessmentAnswerKey(assessmentId, questionId)] != null
        }
        HubActionCard(
            title = item.title ?: "Değerlendirme",
            body = "${item.description ?: ""}\n${if (item.required) "Zorunlu" else "Opsiyonel"} · ${item.durationMinutes ?: 0} dk",
            status = if (canRetry) {
                "retry_available"
            } else {
                item.status
            },
            buttonText = when {
                isPassed -> "Tamamlandı"
                isSubmitting -> "Gönderiliyor..."
                canRetry && requiredQuestionsAnswered ->
                    "Tekrar Gönder"
                canRetry -> "Tekrar için cevapla"
                else -> "Cevapları Gönder"
            },
            enabled = !isPassed &&
                activeActionKey == null &&
                !assessmentId.isNullOrBlank() &&
                requiredQuestionsAnswered,
            onClick = {
                if (!assessmentId.isNullOrBlank()) {
                    val answers = item.questions.mapNotNull { assessmentQuestion ->
                        val questionId = assessmentQuestion.id ?: return@mapNotNull null
                        val optionId = assessmentAnswers[assessmentAnswerKey(assessmentId, questionId)]
                            ?: return@mapNotNull null
                        AssessmentAnswerRequest(questionId = questionId, optionId = optionId)
                    }
                    onCompleteAssessment(assessmentId, answers)
                }
            },
            content = {
                item.score?.let { score ->
                    Text(
                        text = "Skor: %$score${item.passScore?.let { " / Eşik: %$it" } ?: ""}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
                item.passed?.let { passed ->
                    Text(
                        text = if (passed) "Sonuç: geçti" else "Sonuç: kontrol gerekli",
                        style = MaterialTheme.typography.bodySmall,
                        color = if (passed) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
                    )
                }
                item.attemptCount?.let { attemptCount ->
                    Text(
                        text = "Deneme sayısı: $attemptCount",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme
                            .onSurfaceVariant,
                    )
                }
                item.questions.forEach { assessmentQuestion ->
                    Spacer(modifier = Modifier.height(10.dp))
                    Text(
                        text = assessmentQuestion.prompt ?: "Soru",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    assessmentQuestion.options.forEach { option ->
                        val questionId = assessmentQuestion.id
                        val optionId = option.id
                        val selected = !assessmentId.isNullOrBlank() &&
                            !questionId.isNullOrBlank() &&
                            assessmentAnswers[assessmentAnswerKey(assessmentId, questionId)] == optionId
                        val optionLabel = option.label ?: "Seçenek"
                        if (selected) {
                            Button(
                                onClick = {},
                                enabled = !isPassed &&
                                    activeActionKey == null,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 2.dp)
                                    .testTag(
                                        "assessment_option_" +
                                            "${assessmentId.orEmpty()}_" +
                                            "${questionId.orEmpty()}_" +
                                            optionId.orEmpty()
                                    )
                            ) {
                                Text(optionLabel)
                            }
                        } else {
                            OutlinedButton(
                                onClick = {
                                    if (!assessmentId.isNullOrBlank() && !questionId.isNullOrBlank() && !optionId.isNullOrBlank()) {
                                        assessmentAnswers = assessmentAnswers + (
                                            assessmentAnswerKey(assessmentId, questionId) to optionId
                                        )
                                    }
                                },
                                enabled = !isPassed &&
                                    activeActionKey == null,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 2.dp)
                                    .testTag(
                                        "assessment_option_" +
                                            "${assessmentId.orEmpty()}_" +
                                            "${questionId.orEmpty()}_" +
                                            optionId.orEmpty()
                                    )
                            ) {
                                Text(optionLabel)
                            }
                        }
                    }
                }
            }
        )
    }
    if (hub.assessments.isEmpty()) {
        HubSummaryCard(title = "Değerlendirmeler", body = "Bekleyen değerlendirme yok")
    }

    hub.trainings.forEach { item ->
        val trainingId = item.id
        val moduleIds = item.modules.mapNotNull { module -> module.id }
        val isCompleted = item.status == "completed"
        val actionKey = trainingId?.let(::trainingActionKey)
        val isSubmitting = actionKey != null &&
            activeActionKey == actionKey
        val allModulesReviewed = !trainingId.isNullOrBlank() &&
            moduleIds.isNotEmpty() &&
            moduleIds.all { moduleId ->
                trainingModuleKey(trainingId, moduleId) in reviewedTrainingModules
            }
        val selectedModuleIds = if (trainingId.isNullOrBlank()) {
            emptyList()
        } else {
            moduleIds.filter { moduleId ->
                trainingModuleKey(
                    trainingId,
                    moduleId,
                ) in reviewedTrainingModules
            }
        }
        val progressChanged =
            selectedModuleIds.toSet() !=
                item.completedModules.toSet()
        HubActionCard(
            title = item.title ?: "Eğitim",
            body = "${item.description ?: ""}\n${item.durationMinutes ?: 0} dk · İlerleme: %${item.progressPercent ?: 0}",
            status = item.status,
            buttonText = when {
                isCompleted -> "Tamamlandı"
                isSubmitting -> "Gönderiliyor..."
                allModulesReviewed -> "Eğitimi Tamamla"
                else -> "İlerlemeyi Kaydet"
            },
            enabled = !isCompleted &&
                activeActionKey == null &&
                !trainingId.isNullOrBlank() &&
                moduleIds.isNotEmpty() &&
                progressChanged,
            onClick = {
                if (!trainingId.isNullOrBlank()) {
                    onSaveTrainingProgress(
                        trainingId,
                        selectedModuleIds,
                    )
                }
            },
            content = {
                item.modules.forEach { module ->
                    Spacer(modifier = Modifier.height(8.dp))
                    val moduleId = module.id
                    val moduleKey = if (
                        trainingId.isNullOrBlank() || moduleId.isNullOrBlank()
                    ) {
                        null
                    } else {
                        trainingModuleKey(trainingId, moduleId)
                    }
                    val reviewed = moduleKey != null &&
                        moduleKey in reviewedTrainingModules
                    Row(
                        verticalAlignment = Alignment.Top,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Checkbox(
                            checked = reviewed || isCompleted,
                            onCheckedChange = { checked ->
                                if (moduleKey != null) {
                                    reviewedTrainingModules =
                                        if (checked) {
                                            reviewedTrainingModules + moduleKey
                                        } else {
                                            reviewedTrainingModules - moduleKey
                                        }
                                }
                            },
                            enabled = !isCompleted &&
                                activeActionKey == null &&
                                moduleKey != null,
                            modifier = Modifier.testTag(
                                "training_module_" +
                                    "${trainingId.orEmpty()}_" +
                                    moduleId.orEmpty()
                            ),
                        )
                        Column(
                            modifier = Modifier
                                .weight(1f)
                                .padding(top = 10.dp)
                        ) {
                            Text(
                                text = module.title ?: "Modül",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            if (!module.body.isNullOrBlank()) {
                                Text(
                                    text = module.body,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }
                }
            }
        )
    }
    if (hub.trainings.isEmpty()) {
        HubSummaryCard(title = "Eğitimler", body = "Atanmış eğitim yok")
    }

    HubSummaryCard(
        title = "Faydalı Bilgiler",
        body = hub.usefulInfo.joinToString("\n") { item ->
            "${item.title ?: "Bilgi"}: ${item.body ?: ""}"
        }.ifBlank { "Bilgi bulunmuyor" }
    )
    hub.shuttle?.let { shuttle ->
        Text(text = shuttle.title ?: "Servis", style = MaterialTheme.typography.titleMedium)
        Text(
            text = shuttle.description ?: "",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        OutlinedTextField(
            value = shuttleNote,
            onValueChange = { shuttleNote = it },
            label = { Text("Servis notu / durak detayı") },
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            enabled = shuttle.enabled && activeActionKey == null
        )
        if (!shuttle.selectedRouteName.isNullOrBlank()) {
            Text(
                text = "Seçili servis: ${shuttle.selectedRouteName} (${(shuttle.requestStatus ?: "requested").toStatusLabel()})",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary
            )
            if (!shuttle.pickupNote.isNullOrBlank()) {
                Text(
                    text = "Not: ${shuttle.pickupNote}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (!shuttle.decisionNote.isNullOrBlank()) {
                Text(
                    text = "İşveren notu: ${shuttle.decisionNote}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (
                !shuttle.requestId.isNullOrBlank() &&
                shuttle.requestStatus in setOf(
                    "requested",
                    "confirmed",
                )
            ) {
                val cancellationKey =
                    shuttleCancelActionKey(shuttle.requestId)
                OutlinedButton(
                    onClick = {
                        pendingShuttleCancellationId =
                            shuttle.requestId
                    },
                    enabled = activeActionKey == null,
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor =
                            MaterialTheme.colorScheme.error,
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp)
                        .testTag("shuttle_cancel_open"),
                ) {
                    Text(
                        if (activeActionKey == cancellationKey) {
                            "İptal ediliyor..."
                        } else {
                            "Servis Talebini İptal Et"
                        }
                    )
                }
            }
        }
        shuttle.routes.forEach { route ->
            val routeId = route.id
            val actionKey = routeId?.let(::shuttleActionKey)
            val isSubmitting = actionKey != null &&
                activeActionKey == actionKey
            val isSelectedRoute = route.id == shuttle.selectedRouteId
            val canRequestRoute = !isSelectedRoute ||
                shuttle.requestStatus in setOf(
                    "rejected",
                    "cancelled",
                )
            HubActionCard(
                title = route.name ?: "Servis",
                body = route.pickupWindow ?: "Saat belirtilmedi",
                status = if (isSelectedRoute) shuttle.requestStatus ?: "requested" else null,
                buttonText = when {
                    isSubmitting -> "Gönderiliyor..."
                    isSelectedRoute &&
                        shuttle.requestStatus != "rejected" -> "Seçildi"
                    else -> "Servis İste"
                },
                enabled = canRequestRoute &&
                    shuttle.enabled &&
                    activeActionKey == null,
                onClick = {
                    routeId?.let {
                        onRequestShuttle(it, shuttleNote.trim())
                    }
                }
            )
        }
    }
    pendingShuttleCancellationId?.let { requestId ->
        AlertDialog(
            onDismissRequest = {
                pendingShuttleCancellationId = null
            },
            title = { Text("Servis talebini iptal et") },
            text = {
                Text(
                    "Aktif servis talebiniz iptal edilecek. " +
                        "Gerekirse daha sonra yeniden talep oluşturabilirsiniz."
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        pendingShuttleCancellationId = null
                        onCancelShuttle(requestId)
                    },
                    modifier = Modifier.testTag(
                        "shuttle_cancel_confirm"
                    ),
                ) {
                    Text("Talebi İptal Et")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        pendingShuttleCancellationId = null
                    }
                ) {
                    Text("Vazgeç")
                }
            },
        )
    }

    if (!actionMessage.isNullOrBlank()) {
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = actionMessage,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary
        )
    }

    Spacer(modifier = Modifier.height(8.dp))
    OutlinedTextField(
        value = question,
        onValueChange = onQuestionChange,
        label = { Text("Sorunu yaz") },
        modifier = Modifier.fillMaxWidth()
    )
    Spacer(modifier = Modifier.height(8.dp))
    Button(
        onClick = onAskQuestion,
        enabled = question.isNotBlank() && !isAsking,
        modifier = Modifier.fillMaxWidth()
    ) {
        if (isAsking) {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
                color = MaterialTheme.colorScheme.onPrimary
            )
        } else {
            Text("Soru Sor")
        }
    }
    if (!answer.isNullOrBlank()) {
        Spacer(modifier = Modifier.height(8.dp))
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
        ) {
            Text(
                text = answer,
                modifier = Modifier.padding(16.dp),
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}

@Composable
fun QuestionHistorySection(
    questions: List<WorkerQuestionDto>,
    pendingQuestionCount: Int = 0
) {
    Text(text = "Son Sorular", style = MaterialTheme.typography.titleMedium)
    if (pendingQuestionCount > 0) {
        Text(
            text = "$pendingQuestionCount soru işveren yanıtı bekliyor",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary
        )
    }
    Spacer(modifier = Modifier.height(8.dp))
    questions.forEach { item ->
        Card(
            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(text = item.question ?: "Soru", style = MaterialTheme.typography.bodyMedium)
                if (item.status == "pending") {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "İşveren yanıtı bekleniyor",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
                if (!item.answer.isNullOrBlank()) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = item.answer,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
fun HubSummaryCard(title: String, body: String) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(text = title, style = MaterialTheme.typography.titleMedium)
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = body,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
internal fun JobApplicationsSection(
    applications: List<JobApplicationDto>,
    withdrawingApplicationId: String? = null,
    onWithdraw: (String) -> Unit = {},
) {
    var pendingWithdrawalId by remember {
        mutableStateOf<String?>(null)
    }
    Text(
        text = "Başvurularım",
        style = MaterialTheme.typography.titleLarge,
    )
    Text(
        text = "İşveren değerlendirme sürecindeki güncel durumlar",
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(modifier = Modifier.height(12.dp))
    applications.forEach { application ->
        val latestStatus = application.statusHistory.lastOrNull()
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 4.dp)
                .testTag(
                    "job_application_${application.id.orEmpty()}"
                ),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface,
            ),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = application.job.title ?: "İş başvurusu",
                    style = MaterialTheme.typography.titleMedium,
                )
                val employerAndLocation = listOfNotNull(
                    application.job.company,
                    application.job.location,
                ).filter { it.isNotBlank() }.joinToString(" • ")
                if (employerAndLocation.isNotBlank()) {
                    Text(
                        text = employerAndLocation,
                        style = MaterialTheme.typography.bodyMedium,
                        color =
                            MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = (
                        application.status ?: "submitted"
                    ).toStatusLabel(),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                )
                latestStatus?.note
                    ?.takeIf { it.isNotBlank() }
                    ?.let { note ->
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = note,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme
                                .onSurfaceVariant,
                        )
                    }
                application.interview
                    ?.takeIf {
                        application.status in setOf(
                            "reviewing",
                            "shortlisted",
                        )
                    }
                    ?.let { interview ->
                        Spacer(modifier = Modifier.height(12.dp))
                        HorizontalDivider()
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 12.dp)
                                .testTag(
                                    "job_application_interview_" +
                                        application.id.orEmpty()
                                ),
                        ) {
                            Text(
                                text = "Görüşme Planı",
                                style = MaterialTheme.typography
                                    .titleSmall,
                            )
                            interview.scheduledAt
                                ?.takeIf { it.isNotBlank() }
                                ?.let { scheduledAt ->
                                    Text(
                                        text = formatInterviewDate(
                                            scheduledAt
                                        ),
                                        style = MaterialTheme.typography
                                            .bodyMedium,
                                        color = MaterialTheme.colorScheme
                                            .primary,
                                    )
                                }
                            Text(
                                text = interviewTypeLabel(
                                    interview.type
                                ),
                                style = MaterialTheme.typography
                                    .bodySmall,
                                color = MaterialTheme.colorScheme
                                    .onSurfaceVariant,
                            )
                            interview.location
                                ?.takeIf { it.isNotBlank() }
                                ?.let { location ->
                                    Text(
                                        text = "Konum: $location",
                                        style = MaterialTheme.typography
                                            .bodySmall,
                                    )
                                }
                            interview.note
                                ?.takeIf { it.isNotBlank() }
                                ?.let { interviewNote ->
                                    Text(
                                        text = interviewNote,
                                        style = MaterialTheme.typography
                                            .bodySmall,
                                        color = MaterialTheme.colorScheme
                                            .onSurfaceVariant,
                                    )
                                }
                        }
                    }
                val applicationId = application.id
                if (
                    !applicationId.isNullOrBlank() &&
                    application.status in
                    ACTIVE_JOB_APPLICATION_STATUSES
                ) {
                    Spacer(modifier = Modifier.height(10.dp))
                    OutlinedButton(
                        onClick = {
                            pendingWithdrawalId = applicationId
                        },
                        enabled =
                            withdrawingApplicationId == null,
                        colors =
                            ButtonDefaults.outlinedButtonColors(
                                contentColor = MaterialTheme
                                    .colorScheme.error,
                            ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag(
                                "job_application_withdraw_" +
                                    applicationId
                            ),
                    ) {
                        Text(
                            if (
                                withdrawingApplicationId ==
                                applicationId
                            ) {
                                "Geri çekiliyor..."
                            } else {
                                "Başvuruyu Geri Çek"
                            }
                        )
                    }
                }
            }
        }
    }
    pendingWithdrawalId?.let { applicationId ->
        val application = applications.firstOrNull {
            it.id == applicationId
        }
        AlertDialog(
            onDismissRequest = {
                pendingWithdrawalId = null
            },
            title = { Text("Başvuruyu geri çek") },
            text = {
                Text(
                    "${application?.job?.title ?: "Bu iş"} " +
                        "başvurusu geri çekilecek. " +
                        "Bu işlemden sonra yeniden başvuru yapılamaz."
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        pendingWithdrawalId = null
                        onWithdraw(applicationId)
                    },
                    modifier = Modifier.testTag(
                        "job_application_withdraw_confirm"
                    ),
                ) {
                    Text("Geri Çek")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        pendingWithdrawalId = null
                    }
                ) {
                    Text("Vazgeç")
                }
            },
        )
    }
}

@Composable
fun JobRecommendationCard(job: JobDto, isApplying: Boolean, onApply: () -> Unit) {
    val isApplied = job.applicationStatus != null && job.applicationStatus != "not_applied"
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.Top,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = job.title ?: "İş önerisi",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = listOfNotNull(job.company, job.location).joinToString(" • "),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                job.matchScore?.let { score ->
                    Text(
                        text = "%$score",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
            }
            if (!job.reason.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = job.reason,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (isApplied) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Başvuru durumu: ${job.applicationStatus?.toStatusLabel() ?: "Başvuruldu"}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary
                )
            }
            Spacer(modifier = Modifier.height(10.dp))
            Button(
                onClick = onApply,
                enabled = !isApplied && !isApplying && !job.id.isNullOrBlank(),
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("job_apply_button_${job.id.orEmpty()}")
            ) {
                if (isApplying) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary
                    )
                } else {
                    Text(if (isApplied) "Başvuruldu" else "Başvur")
                }
            }
        }
    }
}

@Composable
fun HubActionCard(
    title: String,
    body: String,
    status: String?,
    buttonText: String,
    enabled: Boolean,
    onClick: () -> Unit,
    content: @Composable ColumnScope.() -> Unit = {}
) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.Top,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(text = title, style = MaterialTheme.typography.titleMedium)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = body,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    if (!status.isNullOrBlank()) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = status.toStatusLabel(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                }
            }
            content()
            Spacer(modifier = Modifier.height(8.dp))
            Button(onClick = onClick, enabled = enabled, modifier = Modifier.fillMaxWidth()) {
                Text(buttonText)
            }
        }
    }
}

@Composable
fun DashboardCard(title: String, status: String, icon: ImageVector) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(40.dp), tint = MaterialTheme.colorScheme.primary)
            Spacer(modifier = Modifier.width(16.dp))
            Column {
                Text(text = title, style = MaterialTheme.typography.titleMedium)
                Text(text = status, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
            }
        }
    }
}

private fun createVideoPart(file: File): MultipartBody.Part {
    require(file.exists()) { "Video dosyası bulunamadı." }
    val requestBody = file.asRequestBody("video/mp4".toMediaTypeOrNull())
    return MultipartBody.Part.createFormData("video", file.name, requestBody)
}

private fun createVideoOutputOptions(file: File): FileOutputOptions {
    return FileOutputOptions.Builder(file)
        .setDurationLimitMillis(VIDEO_RECORDING_MAX_DURATION_MS)
        .setFileSizeLimit(VIDEO_RECORDING_MAX_FILE_SIZE_BYTES)
        .build()
}

internal fun formatRecordingDuration(elapsedSeconds: Long): String {
    val boundedSeconds = elapsedSeconds.coerceAtLeast(0)
    return "%02d:%02d".format(
        boundedSeconds / 60,
        boundedSeconds % 60,
    )
}

internal fun shouldAcceptRecordingFinalize(
    error: Int,
    screenActive: Boolean,
): Boolean {
    return screenActive && error in setOf(
        VideoRecordEvent.Finalize.ERROR_NONE,
        VideoRecordEvent.Finalize.ERROR_DURATION_LIMIT_REACHED,
        VideoRecordEvent.Finalize.ERROR_FILE_SIZE_LIMIT_REACHED,
    )
}

internal fun shouldLogRecordingError(error: Int): Boolean {
    return error !in setOf(
        VideoRecordEvent.Finalize.ERROR_NONE,
        VideoRecordEvent.Finalize.ERROR_SOURCE_INACTIVE,
        VideoRecordEvent.Finalize.ERROR_DURATION_LIMIT_REACHED,
        VideoRecordEvent.Finalize.ERROR_FILE_SIZE_LIMIT_REACHED,
    )
}

internal fun resendButtonLabel(secondsRemaining: Int): String {
    return if (secondsRemaining > 0) {
        "Kodu Tekrar Gönder (${secondsRemaining} sn)"
    } else {
        "Kodu Tekrar Gönder"
    }
}

private fun assessmentAnswerKey(assessmentId: String, questionId: String): String {
    return "$assessmentId:$questionId"
}

private fun trainingModuleKey(trainingId: String, moduleId: String): String {
    return "$trainingId:$moduleId"
}

private fun assessmentActionKey(assessmentId: String): String {
    return "assessment:$assessmentId"
}

private fun trainingActionKey(trainingId: String): String {
    return "training:$trainingId"
}

private fun shuttleActionKey(routeId: String): String {
    return "shuttle:$routeId"
}

private fun shuttleCancelActionKey(requestId: String): String {
    return "shuttle-cancel:$requestId"
}

internal fun dashboardRefreshDelay(
    dashboard: DashboardResponse
): Long? {
    return when {
        dashboard.latestVideo?.status == "processing" ->
            VIDEO_PROCESSING_REFRESH_MS
        dashboard.pendingQuestionCount > 0 ->
            PENDING_QUESTION_REFRESH_MS
        dashboard.recommendedJobs.any {
            it.applicationStatus in ACTIVE_JOB_APPLICATION_STATUSES
        } || dashboard.jobApplications.any {
            it.status in ACTIVE_JOB_APPLICATION_STATUSES
        } || dashboard.workerHub?.shuttle?.requestStatus == "requested" ||
            dashboard.workerHub?.trainings.orEmpty().any {
                it.status == "in_progress"
            } ->
            ACTIVE_WORKFLOW_REFRESH_MS
        else -> null
    }
}

private fun String.toStatusLabel(): String {
    return when (this) {
        "registered" -> "Kayıt tamamlandı"
        "not_uploaded" -> "Video yüklenmedi"
        "video_processing", "processing" -> "Video işleniyor"
        "profile_ready" -> "Profil hazır"
        "video_processing_failed" -> "Video işleme başarısız"
        "available" -> "Hazır"
        "requested" -> "İstek alındı"
        "confirmed" -> "Onaylandı"
        "replaced" -> "Değiştirildi"
        "cancelled" -> "İptal edildi"
        "in_progress" -> "Devam ediyor"
        "not_applied" -> "Başvurulmadı"
        "submitted" -> "Başvuru alındı"
        "reviewing" -> "İncelemede"
        "shortlisted" -> "Ön listeye alındı"
        "rejected" -> "Olumsuz"
        "hired" -> "İşe alındı"
        "withdrawn" -> "Geri çekildi"
        "retry_available" -> "Tekrar gerekli"
        "completed" -> "Tamamlandı"
        "failed" -> "Başarısız"
        else -> this
    }
}

internal fun formatInterviewDate(value: String): String {
    val normalized = value.replace(
        Regex("\\.(\\d{3})\\d+(?=[Z+-])"),
        ".$1",
    )
    val parsed = listOf(
        "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
        "yyyy-MM-dd'T'HH:mm:ssXXX",
    ).firstNotNullOfOrNull { pattern ->
        runCatching {
            SimpleDateFormat(pattern, Locale.US).apply {
                isLenient = false
            }.parse(normalized)
        }.getOrNull()
    } ?: return value
    return SimpleDateFormat(
        "dd.MM.yyyy HH:mm",
        Locale.forLanguageTag("tr-TR"),
    ).format(parsed)
}

private fun interviewTypeLabel(value: String?): String = when (value) {
    "onsite" -> "Yüz yüze görüşme"
    "phone" -> "Telefon görüşmesi"
    "video" -> "Video görüşme"
    else -> "Görüşme"
}
