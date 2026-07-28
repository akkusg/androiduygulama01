package com.example.m7_24.api

import com.example.m7_24.BuildConfig
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.UUID
import java.util.concurrent.TimeUnit

object BackendClient {
    @Volatile
    private var accessToken: String? = null

    @Volatile
    private var unauthorizedHandler: (() -> Unit)? = null

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        redactHeader("Authorization")
        level = if (BuildConfig.DEBUG) {
            HttpLoggingInterceptor.Level.HEADERS
        } else {
            HttpLoggingInterceptor.Level.NONE
        }
    }

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.MINUTES)
        .addInterceptor { chain ->
            val token = accessToken
            val requestBuilder = chain.request().newBuilder()
                .header("X-App-Platform", "android")
                .header(
                    "X-App-Version-Code",
                    BuildConfig.VERSION_CODE.toString(),
                )
                .header("X-App-Version-Name", BuildConfig.VERSION_NAME)
            if (!token.isNullOrBlank()) {
                requestBuilder
                    .header("Authorization", "Bearer $token")
            }
            val request = requestBuilder.build()
            chain.proceed(request).also { response ->
                if (response.code == 401 && !token.isNullOrBlank()) {
                    unauthorizedHandler?.invoke()
                }
            }
        }
        .addInterceptor(loggingInterceptor)
        .build()

    val api: BackendApi = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(httpClient)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(BackendApi::class.java)

    fun setAccessToken(token: String?) {
        accessToken = token
    }

    fun setUnauthorizedHandler(handler: (() -> Unit)?) {
        unauthorizedHandler = handler
    }

    fun newIdempotencyKey(): String = UUID.randomUUID().toString()
}
