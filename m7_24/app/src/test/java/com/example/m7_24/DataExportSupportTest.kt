package com.example.m7_24

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import kotlin.io.path.createTempDirectory

class DataExportSupportTest {
    @Test
    fun writesBoundedJsonAndCleansExpiredExport() {
        val cacheDir = createTempDirectory("data-export-").toFile()
        val now = 2 * DATA_EXPORT_MAX_AGE_MS
        try {
            val output = writeWorkerDataExport(
                cacheDir,
                ByteArrayInputStream("""{"schemaVersion":1}""".toByteArray()),
                nowMillis = 0,
            )
            output.setLastModified(0)

            assertEquals(
                """{"schemaVersion":1}""",
                output.readText(),
            )
            assertEquals(
                1,
                cleanupStaleDataExports(cacheDir, now),
            )
            assertFalse(output.exists())
        } finally {
            cacheDir.deleteRecursively()
        }
    }

    @Test
    fun removesPartialFileWhenExportExceedsLimit() {
        val cacheDir = createTempDirectory("data-export-limit-")
            .toFile()
        try {
            assertThrows(IllegalArgumentException::class.java) {
                writeWorkerDataExport(
                    cacheDir,
                    ByteArrayInputStream("123456".toByteArray()),
                    nowMillis = 1,
                    maxBytes = 5,
                )
            }
            assertTrue(
                File(cacheDir, "exports").list().isNullOrEmpty()
            )
        } finally {
            cacheDir.deleteRecursively()
        }
    }
}
