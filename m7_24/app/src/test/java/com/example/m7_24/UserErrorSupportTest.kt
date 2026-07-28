package com.example.m7_24

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UserErrorSupportTest {
    @Test
    fun rateLimitIncludesServerControlledWait() {
        assertEquals(
            "Çok fazla deneme yapıldı. 17 saniye sonra tekrar deneyin.",
            httpUserMessage(
                statusCode = 429,
                fallback = "Kod gönderilemedi.",
                retryAfterSeconds = 17,
            ),
        )
    }

    @Test
    fun serverFailureIncludesOnlySafeSupportCode() {
        assertEquals(
            "Sunucuda geçici bir hata oluştu. Lütfen daha sonra tekrar deneyin. " +
                "Destek kodu: request-1234",
            httpUserMessage(
                statusCode = 503,
                fallback = "Panel alınamadı.",
                requestId = "request-1234",
            ),
        )
        assertFalse(
            httpUserMessage(
                statusCode = 500,
                fallback = "Panel alınamadı.",
                requestId = "unsafe request id",
            ).contains("unsafe"),
        )
    }

    @Test
    fun validatesSupportedPhoneInputShapes() {
        listOf(
            "+90 555 111 22 33",
            "0090 555 111 22 33",
            "90 555 111 22 33",
            "0555 111 22 33",
            "555 111 22 33",
        ).forEach { phone ->
            assertTrue(phone, isPlausiblePhoneInput(phone))
        }
        listOf(
            "+095551112233",
            "+90555923017",
            "0555",
            "phone",
            "",
        ).forEach { phone ->
            assertFalse(phone, isPlausiblePhoneInput(phone))
        }
    }
}
