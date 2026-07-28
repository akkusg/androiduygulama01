package com.example.m7_24

import com.example.m7_24.api.MobileConfigResponse

internal sealed interface AppAvailability {
    data object Available : AppAvailability

    data class Maintenance(
        val message: String,
    ) : AppAvailability

    data class UpdateRequired(
        val message: String,
        val updateUrl: String,
    ) : AppAvailability
}

internal fun evaluateAppAvailability(
    config: MobileConfigResponse,
    installedVersionCode: Int,
): AppAvailability {
    if (config.maintenanceMode) {
        return AppAvailability.Maintenance(
            message = config.maintenanceMessage.ifBlank {
                "Planlı bakım nedeniyle kısa süre içinde tekrar deneyin."
            },
        )
    }
    if (installedVersionCode < config.minSupportedVersionCode) {
        return AppAvailability.UpdateRequired(
            message = config.updateMessage.ifBlank {
                "Devam etmek için uygulamanın güncel sürümünü yükleyin."
            },
            updateUrl = config.updateUrl,
        )
    }
    return AppAvailability.Available
}
