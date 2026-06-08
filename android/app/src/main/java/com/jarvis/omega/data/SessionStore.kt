package com.jarvis.omega.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking

private val Context.dataStore by preferencesDataStore("jarvis_session")

class SessionStore(private val context: Context) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val securePrefs = EncryptedSharedPreferences.create(
        context,
        "jarvis_secure",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    companion object {
        private val KEY_CLERK_TOKEN = stringPreferencesKey("clerk_jwt")
        private val KEY_DEVICE_ID = stringPreferencesKey("device_id")
        private val KEY_BASE_URL = stringPreferencesKey("base_url")
        private val KEY_DESKTOP_ID = stringPreferencesKey("desktop_device_id")
        private val KEY_USER_ID = stringPreferencesKey("user_id")

        const val PREF_ACCESS_TOKEN = "access_token"
        const val PREF_DEVICE_SECRET = "device_secret"
        const val PREF_REFRESH_TOKEN = "refresh_token"
    }

    val clerkTokenFlow: Flow<String?> = context.dataStore.data.map { it[KEY_CLERK_TOKEN] }
    val deviceIdFlow: Flow<String?> = context.dataStore.data.map { it[KEY_DEVICE_ID] }
    val baseUrlFlow: Flow<String?> = context.dataStore.data.map { it[KEY_BASE_URL] }
    val isPairedFlow: Flow<Boolean> = context.dataStore.data.map {
        !it[KEY_BASE_URL].isNullOrBlank() && !it[KEY_DEVICE_ID].isNullOrBlank()
    }

    suspend fun saveClerkToken(token: String) {
        context.dataStore.edit { it[KEY_CLERK_TOKEN] = token.trim() }
    }

    suspend fun savePairingConfig(
        userId: String,
        desktopDeviceId: String,
        baseUrl: String,
        mobileDeviceId: String,
    ) {
        context.dataStore.edit {
            it[KEY_USER_ID] = userId
            it[KEY_DESKTOP_ID] = desktopDeviceId
            it[KEY_BASE_URL] = baseUrl.trimEnd('/')
            it[KEY_DEVICE_ID] = mobileDeviceId
        }
    }

    fun saveDeviceTokens(accessToken: String, refreshToken: String, deviceSecret: String) {
        securePrefs.edit()
            .putString(PREF_ACCESS_TOKEN, accessToken)
            .putString(PREF_REFRESH_TOKEN, refreshToken)
            .putString(PREF_DEVICE_SECRET, deviceSecret)
            .apply()
    }

    fun getClerkToken(): String? = runBlocking {
        context.dataStore.data.first()[KEY_CLERK_TOKEN]
    }

    fun getDeviceId(): String? = runBlocking {
        context.dataStore.data.first()[KEY_DEVICE_ID]
    }

    fun getBaseUrl(): String? = runBlocking {
        context.dataStore.data.first()[KEY_BASE_URL]
    }

    fun getDesktopDeviceId(): String? = runBlocking {
        context.dataStore.data.first()[KEY_DESKTOP_ID]
    }

    fun getAccessToken(): String? = securePrefs.getString(PREF_ACCESS_TOKEN, null)

    suspend fun clear() {
        context.dataStore.edit { it.clear() }
        securePrefs.edit().clear().apply()
    }
}
