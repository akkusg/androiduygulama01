package com.example.m7_24

import com.google.gson.JsonParser
import java.io.IOException
import retrofit2.HttpException

internal fun Throwable.toUserMessage(fallback: String): String {
    return when (this) {
        is HttpException -> {
            val requestId = runCatching {
                JsonParser.parseString(
                    response()?.errorBody()?.string(),
                )
                    .asJsonObject
                    .get("requestId")
                    ?.asString
            }.getOrNull()
            httpUserMessage(
                statusCode = code(),
                fallback = fallback,
                retryAfterSeconds = retryAfterSeconds(),
                requestId = requestId,
            )
        }

        is IOException ->
            "Sunucuya bağlanılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin."

        is IllegalArgumentException -> message ?: fallback
        else -> fallback
    }
}

internal fun Throwable.retryAfterSeconds(): Int? {
    return (this as? HttpException)
        ?.response()
        ?.headers()
        ?.get("Retry-After")
        ?.toIntOrNull()
}

internal fun httpUserMessage(
    statusCode: Int,
    fallback: String,
    retryAfterSeconds: Int? = null,
    requestId: String? = null,
): String {
    val message = when (statusCode) {
        400, 401, 422 -> fallback
        403 -> "Bu işlem için yetkiniz yok."
        404 -> "İstenen bilgi bulunamadı."
        409 -> "$fallback İşlem daha önce tamamlanmış veya başka bir istekle çakışmış olabilir."
        413 -> "Gönderilen dosya izin verilen boyutu aşıyor."
        429 -> {
            if (retryAfterSeconds != null && retryAfterSeconds > 0) {
                "Çok fazla deneme yapıldı. $retryAfterSeconds saniye sonra tekrar deneyin."
            } else {
                "Çok fazla deneme yapıldı. Lütfen daha sonra tekrar deneyin."
            }
        }

        in 500..599 ->
            "Sunucuda geçici bir hata oluştu. Lütfen daha sonra tekrar deneyin."

        else -> "$fallback ($statusCode)"
    }
    val safeRequestId = requestId
        ?.takeIf { it.matches(Regex("[A-Za-z0-9._:-]{8,128}")) }
    return if (statusCode >= 500 && safeRequestId != null) {
        "$message Destek kodu: $safeRequestId"
    } else {
        message
    }
}
