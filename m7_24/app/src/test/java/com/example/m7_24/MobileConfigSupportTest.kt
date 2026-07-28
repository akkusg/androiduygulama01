package com.example.m7_24

import com.example.m7_24.api.MobileConfigResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test

class MobileConfigSupportTest {
    @Test
    fun allowsInstalledVersionAtMinimum() {
        val result = evaluateAppAvailability(
            config = config(minimum = 7),
            installedVersionCode = 7,
        )

        assertSame(AppAvailability.Available, result)
    }

    @Test
    fun requiresUpdateBelowMinimum() {
        val result = evaluateAppAvailability(
            config = config(minimum = 8),
            installedVersionCode = 7,
        ) as AppAvailability.UpdateRequired

        assertEquals("Güncelleme gerekli.", result.message)
        assertEquals("https://example.com/app", result.updateUrl)
    }

    @Test
    fun maintenanceTakesPriorityOverVersion() {
        val result = evaluateAppAvailability(
            config = config(
                minimum = 8,
                maintenance = true,
            ),
            installedVersionCode = 7,
        ) as AppAvailability.Maintenance

        assertEquals("Bakım yapılıyor.", result.message)
    }

    private fun config(
        minimum: Int,
        maintenance: Boolean = false,
    ) = MobileConfigResponse(
        platform = "android",
        minSupportedVersionCode = minimum,
        latestVersionCode = minimum,
        maintenanceMode = maintenance,
        maintenanceMessage = "Bakım yapılıyor.",
        updateMessage = "Güncelleme gerekli.",
        updateUrl = "https://example.com/app",
        privacyPolicyUrl = "https://example.com/privacy",
        videoConsentVersion = "video-processing-v1",
    )
}
