package com.example.m7_24

import java.io.File
import java.security.MessageDigest

internal const val CAPTURED_VIDEO_PREFIX = "cv_video_"
internal const val CAPTURED_VIDEO_MAX_AGE_MS = 24L * 60 * 60 * 1000

internal fun sha256Hex(file: File): String {
    require(file.isFile) { "Video dosyası bulunamadı." }
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().buffered().use { input ->
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        while (true) {
            val bytesRead = input.read(buffer)
            if (bytesRead < 0) break
            digest.update(buffer, 0, bytesRead)
        }
    }
    return digest.digest().joinToString("") { byte ->
        "%02x".format(byte.toInt() and 0xff)
    }
}

internal fun deleteCapturedVideo(file: File): Boolean {
    return !file.exists() || file.delete()
}

internal fun cleanupStaleCapturedVideos(
    cacheDir: File,
    nowMillis: Long = System.currentTimeMillis(),
    maxAgeMillis: Long = CAPTURED_VIDEO_MAX_AGE_MS,
): Int {
    val capturedVideos = cacheDir.listFiles { file ->
        file.isFile &&
            file.name.startsWith(CAPTURED_VIDEO_PREFIX) &&
            file.name.endsWith(".mp4") &&
            nowMillis - file.lastModified() >= maxAgeMillis
    }.orEmpty()
    return capturedVideos.count(::deleteCapturedVideo)
}
