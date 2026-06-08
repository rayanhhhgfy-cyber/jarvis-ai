package com.jarvis.omega.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ApiClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    suspend fun consumePairing(
        baseUrl: String,
        clerkToken: String,
        pairingSecret: String,
        mobileDeviceId: String,
        deviceName: String,
    ): PairingResult = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("pairing_secret", pairingSecret)
            .put("mobile_device_id", mobileDeviceId)
            .put("device_name", deviceName)
            .put("platform", "android")
            .toString()

        val request = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/api/devices/pair/consume")
            .post(body.toRequestBody(jsonMedia))
            .header("Authorization", "Bearer $clerkToken")
            .header("Content-Type", "application/json")
            .build()

        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                throw IllegalStateException(detail ?: "Pairing failed (${response.code})")
            }
            val json = JSONObject(text)
            PairingResult(
                deviceId = json.optString("device_id"),
                deviceSecret = json.optString("device_secret"),
                accessToken = json.optString("access_token"),
                refreshToken = json.optString("refresh_token"),
                approved = json.optBoolean("approved", false),
            )
        }
    }

    suspend fun postChat(
        baseUrl: String,
        clerkToken: String,
        message: String,
        deviceId: String,
    ): String = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("message", message)
            .put("device_id", deviceId)
            .put("include_memory", true)
            .put("stream", false)
            .toString()

        val request = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/api/chat")
            .post(body.toRequestBody(jsonMedia))
            .header("Authorization", "Bearer $clerkToken")
            .build()

        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException("Chat failed (${response.code}): $text")
            }
            JSONObject(text).optString("content", "No response")
        }
    }
}

data class PairingResult(
    val deviceId: String,
    val deviceSecret: String,
    val accessToken: String,
    val refreshToken: String,
    val approved: Boolean,
)
