package com.example.m7_24

import java.io.File
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PrivateCacheSupportTest {
    @Test
    fun clearsOnlyWorkerPrivateArtifacts() {
        val cacheDir = createTempDirectory("private-cache-").toFile()
        val exportDir = File(cacheDir, "exports").apply { mkdirs() }
        val video = File(cacheDir, "cv_video_private.mp4").apply {
            writeText("video")
        }
        val export = File(
            exportDir,
            "worker_data_private.json",
        ).apply {
            writeText("export")
        }
        val unrelated = File(cacheDir, "unrelated.cache").apply {
            writeText("keep")
        }

        try {
            assertEquals(2, clearWorkerPrivateCache(cacheDir))
            assertFalse(video.exists())
            assertFalse(export.exists())
            assertFalse(exportDir.exists())
            assertTrue(unrelated.exists())
        } finally {
            cacheDir.deleteRecursively()
        }
    }
}
