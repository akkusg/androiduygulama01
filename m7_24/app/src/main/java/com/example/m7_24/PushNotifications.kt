package com.example.m7_24

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.example.m7_24.api.BackendClient
import com.example.m7_24.api.DeviceRegistrationRequest
import com.google.firebase.installations.FirebaseInstallations
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import retrofit2.HttpException
import java.io.IOException
import java.util.UUID
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine

internal class InstallationStore(context: Context) {
    private val preferences = context.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )

    fun getOrCreateId(): String {
        preferences.getString(KEY_INSTALLATION_ID, null)
            ?.takeIf(::isCanonicalUuid)
            ?.let { return it }
        val installationId = UUID.randomUUID().toString()
        check(
            preferences.edit()
                .putString(KEY_INSTALLATION_ID, installationId)
                .commit()
        )
        return installationId
    }

    private fun isCanonicalUuid(value: String): Boolean = runCatching {
        UUID.fromString(value).toString() == value
    }.getOrDefault(false)

    private companion object {
        const val PREFERENCES_NAME = "m7_24_installation"
        const val KEY_INSTALLATION_ID = "installation_id"
    }
}

internal class PushEventStore(context: Context) {
    private val preferences = context.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )

    @Synchronized
    fun markIfNew(eventId: String): Boolean {
        if (
            eventId.isBlank() ||
            eventId.length > 256 ||
            '\n' in eventId
        ) {
            return false
        }
        val current = preferences.getString(KEY_EVENT_IDS, "")
            .orEmpty()
            .lineSequence()
            .filter { it.isNotBlank() }
            .toList()
        if (eventId in current) return false
        val updated = (current + eventId).takeLast(MAX_EVENT_IDS)
        return preferences.edit()
            .putString(KEY_EVENT_IDS, updated.joinToString("\n"))
            .commit()
    }

    fun clear() {
        preferences.edit().clear().commit()
    }

    private companion object {
        const val PREFERENCES_NAME = "m7_24_push_events"
        const val KEY_EVENT_IDS = "event_ids"
        const val MAX_EVENT_IDS = 100
    }
}

internal object PushRegistrationScheduler {
    private const val REFRESH_WORK_NAME = "push-fid-refresh"
    private const val UPLOAD_WORK_NAME = "push-fid-upload"
    internal const val FID_INPUT_KEY = "firebase-installation-id"

    fun schedule(context: Context) {
        enqueue(context, REFRESH_WORK_NAME, null)
    }

    fun scheduleUpload(context: Context, fid: String) {
        if (fid.isBlank()) return
        enqueue(context, UPLOAD_WORK_NAME, fid)
    }

    private fun enqueue(
        context: Context,
        workName: String,
        fid: String?,
    ) {
        if (!BuildConfig.FCM_ENABLED) return
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val requestBuilder =
            OneTimeWorkRequestBuilder<PushTokenSyncWorker>()
            .setConstraints(constraints)
        if (fid != null) {
            requestBuilder.setInputData(
                workDataOf(FID_INPUT_KEY to fid)
            )
        }
        WorkManager.getInstance(context).enqueueUniqueWork(
            workName,
            ExistingWorkPolicy.REPLACE,
            requestBuilder.build(),
        )
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context)
            .cancelUniqueWork(REFRESH_WORK_NAME)
        WorkManager.getInstance(context)
            .cancelUniqueWork(UPLOAD_WORK_NAME)
    }
}

internal class PushTokenSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        if (!BuildConfig.FCM_ENABLED) return Result.success()
        val sessionStore = SessionStore(applicationContext)
        val userId = sessionStore.getUserId()
        val accessToken = sessionStore.getAccessToken()
        if (userId.isNullOrBlank() || accessToken.isNullOrBlank()) {
            return Result.success()
        }
        BackendClient.setAccessToken(accessToken)
        return try {
            registerPushDevice(
                applicationContext,
                userId,
                inputData.getString(
                    PushRegistrationScheduler.FID_INPUT_KEY
                ),
            )
            Result.success()
        } catch (error: HttpException) {
            if (
                error.code() == 429 ||
                error.code() >= 500
            ) {
                retryWithLimit()
            } else {
                Result.success()
            }
        } catch (error: IOException) {
            retryWithLimit()
        } catch (error: Exception) {
            retryWithLimit()
        }
    }

    private fun retryWithLimit(): Result =
        if (runAttemptCount < 5) Result.retry() else Result.failure()
}

internal suspend fun registerPushDevice(
    context: Context,
    userId: String,
    knownFid: String? = null,
) {
    if (!BuildConfig.FCM_ENABLED) return
    val messaging = FirebaseMessaging.getInstance()
    messaging.setAutoInitEnabled(true)
    val fid = knownFid?.takeIf { it.isNotBlank() } ?: run {
        awaitFirebaseTask(messaging.register())
        awaitFirebaseTask(FirebaseInstallations.getInstance().id)
    }
    BackendClient.api.registerDevice(
        userId = userId,
        installationId = InstallationStore(context).getOrCreateId(),
        request = DeviceRegistrationRequest(
            fid = fid,
            appVersionCode = BuildConfig.VERSION_CODE,
            appVersionName = BuildConfig.VERSION_NAME,
        ),
    )
}

internal suspend fun unregisterPushDevice(
    context: Context,
    userId: String?,
) {
    PushRegistrationScheduler.cancel(context)
    if (
        BuildConfig.FCM_ENABLED &&
        !userId.isNullOrBlank()
    ) {
        BackendClient.api.unregisterDevice(
            userId,
            InstallationStore(context).getOrCreateId(),
        )
    }
}

internal suspend fun unregisterLocalPush() {
    if (!BuildConfig.FCM_ENABLED) return
    val messaging = FirebaseMessaging.getInstance()
    messaging.setAutoInitEnabled(false)
    awaitFirebaseTask(messaging.unregister())
    awaitFirebaseTask(FirebaseInstallations.getInstance().delete())
}

class WorkerFirebaseMessagingService :
    FirebaseMessagingService() {
    override fun onRegistered(installationId: String) {
        if (
            BuildConfig.FCM_ENABLED &&
            installationId.isNotBlank()
        ) {
            PushRegistrationScheduler.scheduleUpload(
                applicationContext,
                installationId,
            )
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        if (!BuildConfig.FCM_ENABLED) return
        val session = SessionStore(applicationContext)
        if (
            session.getUserId().isNullOrBlank() ||
            session.getAccessToken().isNullOrBlank()
        ) {
            return
        }
        val payload = parseWorkerPushPayload(message.data) ?: return
        if (!PushEventStore(applicationContext).markIfNew(payload.eventId)) {
            return
        }
        DashboardNotificationStore(applicationContext)
            .applyPushEvent(payload)
        WorkerNotificationPublisher.publish(
            applicationContext,
            WorkerNotificationEvent(
                key = payload.eventId,
                title = payload.title,
                body = payload.body,
            ),
        )
    }
}

private suspend fun <T> awaitFirebaseTask(
    task: com.google.android.gms.tasks.Task<T>,
): T = suspendCancellableCoroutine { continuation ->
    task.addOnCompleteListener { completed ->
        if (!continuation.isActive) return@addOnCompleteListener
        val error = completed.exception
        if (completed.isSuccessful) {
            continuation.resume(completed.result)
        } else if (error != null) {
            continuation.resumeWithException(error)
        } else {
            continuation.resumeWithException(
                IllegalStateException("Firebase task failed")
            )
        }
    }
}
