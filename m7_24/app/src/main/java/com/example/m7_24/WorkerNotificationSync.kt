package com.example.m7_24

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.example.m7_24.api.BackendClient
import retrofit2.HttpException
import java.io.IOException
import java.util.concurrent.TimeUnit

internal object WorkerNotificationScheduler {
    private const val WORK_NAME = "worker-dashboard-notifications"

    fun schedule(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request =
            PeriodicWorkRequestBuilder<DashboardNotificationWorker>(
                15,
                TimeUnit.MINUTES,
            )
                .setConstraints(constraints)
                .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_NAME,
            ExistingPeriodicWorkPolicy.UPDATE,
            request,
        )
    }

    fun cancelAndClear(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        PushRegistrationScheduler.cancel(context)
        DashboardNotificationStore(context).clear()
        PushEventStore(context).clear()
    }
}

internal class DashboardNotificationWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val sessionStore = SessionStore(applicationContext)
        val userId = sessionStore.getUserId()
        val accessToken = sessionStore.getAccessToken()
        if (userId.isNullOrBlank() || accessToken.isNullOrBlank()) {
            DashboardNotificationStore(applicationContext).clear()
            return Result.success()
        }

        BackendClient.setAccessToken(accessToken)
        return try {
            val dashboard = BackendClient.api.getDashboard(userId)
            val current = dashboard.toNotificationSnapshot()
            val store = DashboardNotificationStore(applicationContext)
            val events = dashboardNotificationEvents(store.load(), current)
            store.save(current)
            events.forEach {
                WorkerNotificationPublisher.publish(
                    applicationContext,
                    it,
                )
            }
            Result.success()
        } catch (error: HttpException) {
            when {
                error.code() == 401 -> {
                    BackendClient.setAccessToken(null)
                    sessionStore.clear()
                    DashboardNotificationStore(applicationContext).clear()
                    Result.success()
                }
                error.code() == 429 || error.code() >= 500 ->
                    retryOrWaitForNextPeriod()
                else -> Result.success()
            }
        } catch (error: IOException) {
            retryOrWaitForNextPeriod()
        } catch (error: Exception) {
            retryOrWaitForNextPeriod()
        }
    }

    private fun retryOrWaitForNextPeriod(): Result =
        if (runAttemptCount < 3) Result.retry() else Result.success()
}

internal object WorkerNotificationPublisher {
    private const val CHANNEL_ID = "worker_updates"
    private const val CHANNEL_NAME = "Çalışan güncellemeleri"

    fun publish(
        context: Context,
        event: WorkerNotificationEvent,
    ) {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val notificationManager =
            NotificationManagerCompat.from(context)
        if (!notificationManager.areNotificationsEnabled()) return

        createChannel(context)
        val launchIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            0,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or
                PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(
            context,
            CHANNEL_ID,
        )
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(event.title)
            .setContentText(event.body)
            .setStyle(
                NotificationCompat.BigTextStyle()
                    .bigText(event.body)
            )
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .build()
        notificationManager.notify(
            event.key.hashCode() and Int.MAX_VALUE,
            notification,
        )
    }

    private fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(
            NotificationManager::class.java
        )
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description =
                    "Başvuru, servis ve işveren yanıtı güncellemeleri"
            }
        )
    }
}
