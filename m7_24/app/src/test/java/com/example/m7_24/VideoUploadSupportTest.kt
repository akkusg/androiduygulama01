package com.example.m7_24

import androidx.camera.video.VideoRecordEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.io.path.createTempDirectory

class VideoUploadSupportTest {
    @Test
    fun sha256HexReturnsStableDigestForVideoFile() {
        val file = File.createTempFile("video-upload-", ".mp4")
        try {
            file.writeBytes("video-content".toByteArray())

            assertEquals(
                "b4367c8908484308c443753ed4d99261251cb04f8"
                    + "707b1d1d189c7a87b556141",
                sha256Hex(file),
            )
        } finally {
            file.delete()
        }
    }

    @Test
    fun cleanupDeletesOnlyExpiredCapturedVideos() {
        val cacheDir = createTempDirectory("video-cache-").toFile()
        val now = 2 * CAPTURED_VIDEO_MAX_AGE_MS
        val expired = File(cacheDir, "cv_video_expired.mp4").apply {
            writeText("expired")
            setLastModified(0)
        }
        val recent = File(cacheDir, "cv_video_recent.mp4").apply {
            writeText("recent")
            setLastModified(now)
        }
        val unrelated = File(cacheDir, "other.mp4").apply {
            writeText("unrelated")
            setLastModified(0)
        }

        try {
            assertEquals(
                1,
                cleanupStaleCapturedVideos(cacheDir, now),
            )
            assertEquals(false, expired.exists())
            assertEquals(true, recent.exists())
            assertEquals(true, unrelated.exists())
        } finally {
            cacheDir.deleteRecursively()
        }
    }

    @Test
    fun recordingDurationFormatsForCameraCounter() {
        assertEquals("00:00", formatRecordingDuration(0))
        assertEquals("01:30", formatRecordingDuration(90))
    }

    @Test
    fun recordingFinalizeClassifiesLimitsAndLifecycleStop() {
        assertTrue(
            shouldAcceptRecordingFinalize(
                VideoRecordEvent.Finalize.ERROR_NONE,
                screenActive = true,
            )
        )
        assertTrue(
            shouldAcceptRecordingFinalize(
                VideoRecordEvent.Finalize.ERROR_DURATION_LIMIT_REACHED,
                screenActive = true,
            )
        )
        assertTrue(
            shouldAcceptRecordingFinalize(
                VideoRecordEvent.Finalize.ERROR_FILE_SIZE_LIMIT_REACHED,
                screenActive = true,
            )
        )
        assertFalse(
            shouldAcceptRecordingFinalize(
                VideoRecordEvent.Finalize.ERROR_SOURCE_INACTIVE,
                screenActive = false,
            )
        )
        assertFalse(
            shouldLogRecordingError(
                VideoRecordEvent.Finalize.ERROR_SOURCE_INACTIVE
            )
        )
        assertTrue(
            shouldLogRecordingError(
                VideoRecordEvent.Finalize.ERROR_ENCODING_FAILED
            )
        )
    }
}
