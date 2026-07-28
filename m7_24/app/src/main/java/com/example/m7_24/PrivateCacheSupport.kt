package com.example.m7_24

import java.io.File

internal fun clearWorkerPrivateCache(cacheDir: File): Int {
    val capturedVideos = cacheDir.listFiles { file ->
        file.isFile &&
            file.name.startsWith(CAPTURED_VIDEO_PREFIX) &&
            file.name.endsWith(".mp4")
    }.orEmpty()
    val exportDir = File(cacheDir, "exports")
    val dataExports = exportDir.listFiles { file ->
        file.isFile &&
            file.name.startsWith("worker_data_") &&
            file.name.endsWith(".json")
    }.orEmpty()

    val privateArtifacts = buildList<File> {
        addAll(capturedVideos)
        addAll(dataExports)
    }
    val deleted = privateArtifacts.count { file ->
        file.delete()
    }
    if (exportDir.list().isNullOrEmpty()) {
        exportDir.delete()
    }
    return deleted
}
