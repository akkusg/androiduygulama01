package com.example.m7_24

import java.io.File
import java.io.InputStream

internal const val DATA_EXPORT_MAX_AGE_MS = 24L * 60 * 60 * 1000
internal const val DATA_EXPORT_MAX_BYTES = 25L * 1024 * 1024

internal fun writeWorkerDataExport(
    cacheDir: File,
    input: InputStream,
    nowMillis: Long = System.currentTimeMillis(),
    maxBytes: Long = DATA_EXPORT_MAX_BYTES,
): File {
    val exportDir = File(cacheDir, "exports")
    check(exportDir.isDirectory || exportDir.mkdirs()) {
        "Veri dışa aktarım klasörü oluşturulamadı."
    }
    val outputFile = File(
        exportDir,
        "worker_data_$nowMillis.json",
    )
    try {
        outputFile.outputStream().buffered().use { output ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            var totalBytes = 0L
            while (true) {
                val bytesRead = input.read(buffer)
                if (bytesRead < 0) break
                totalBytes += bytesRead
                require(totalBytes <= maxBytes) {
                    "Veri dışa aktarımı izin verilen boyutu aşıyor."
                }
                output.write(buffer, 0, bytesRead)
            }
        }
    } catch (error: Exception) {
        outputFile.delete()
        throw error
    }
    return outputFile
}

internal fun cleanupStaleDataExports(
    cacheDir: File,
    nowMillis: Long = System.currentTimeMillis(),
    maxAgeMillis: Long = DATA_EXPORT_MAX_AGE_MS,
): Int {
    val exportDir = File(cacheDir, "exports")
    val staleFiles = exportDir.listFiles { file ->
        file.isFile &&
            file.name.startsWith("worker_data_") &&
            file.name.endsWith(".json") &&
            nowMillis - file.lastModified() >= maxAgeMillis
    }.orEmpty()
    val deleted = staleFiles.count { file ->
        !file.exists() || file.delete()
    }
    if (exportDir.list().isNullOrEmpty()) exportDir.delete()
    return deleted
}
