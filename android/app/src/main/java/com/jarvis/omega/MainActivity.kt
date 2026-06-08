package com.jarvis.omega

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.lifecycleScope
import com.jarvis.omega.actions.AccessibilityExecutor
import com.jarvis.omega.audio.AudioRecorder
import com.jarvis.omega.data.SessionStore
import com.jarvis.omega.network.ApiClient
import com.jarvis.omega.service.JarvisForegroundService
import com.jarvis.omega.ui.AuthScreen
import com.jarvis.omega.ui.ChatBubble
import com.jarvis.omega.ui.ChatScreen
import com.jarvis.omega.ui.ExecutionCard
import com.jarvis.omega.ui.PairingScreen
import com.jarvis.omega.ui.PermissionsBanner
import com.jarvis.omega.ui.theme.JarvisTheme
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import org.json.JSONObject

enum class AppScreen { AUTH, PAIRING, CHAT }

class MainActivity : ComponentActivity() {

    private lateinit var sessionStore: SessionStore
    private val api = ApiClient()
    private var audioRecorder: AudioRecorder? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sessionStore = SessionStore(applicationContext)
        audioRecorder = AudioRecorder(this)

        setContent {
            JarvisTheme {
                val scope = rememberCoroutineScope()
                var screen by remember { mutableStateOf(AppScreen.AUTH) }
                var pairingLoading by remember { mutableStateOf(false) }
                var pairingError by remember { mutableStateOf<String?>(null) }
                var isSending by remember { mutableStateOf(false) }
                var isRecording by remember { mutableStateOf(false) }
                var connected by remember { mutableStateOf(false) }

                val messages = remember { mutableStateListOf<ChatBubble>() }
                val executions = remember { mutableStateListOf<ExecutionCard>() }

                val isPaired by sessionStore.isPairedFlow.collectAsState(initial = false)
                val clerkToken by sessionStore.clerkTokenFlow.collectAsState(initial = null)

                androidx.compose.runtime.LaunchedEffect(clerkToken, isPaired) {
                    screen = when {
                        clerkToken.isNullOrBlank() -> AppScreen.AUTH
                        !isPaired -> AppScreen.PAIRING
                        else -> AppScreen.CHAT
                    }
                    if (isPaired && !clerkToken.isNullOrBlank()) {
                        JarvisForegroundService.start(applicationContext)
                    }
                }

                Column(Modifier.fillMaxSize()) {
                    PermissionsBanner(
                        onEnableAccessibility = {
                            AccessibilityExecutor.openAccessibilitySettings(this@MainActivity)
                        },
                        onEnableNotifications = {
                            AccessibilityExecutor.openNotificationSettings(this@MainActivity)
                        },
                    )

                    when (screen) {
                        AppScreen.AUTH -> AuthScreen(
                            onTokenSaved = { token ->
                                scope.launch {
                                    sessionStore.saveClerkToken(token)
                                    screen = AppScreen.PAIRING
                                }
                            },
                        )

                        AppScreen.PAIRING -> PairingScreen(
                            isLoading = pairingLoading,
                            error = pairingError,
                            onQrScanned = { json ->
                                scope.launch {
                                    pairingLoading = true
                                    pairingError = null
                                    try {
                                        val token = sessionStore.getClerkToken()
                                            ?: throw IllegalStateException("Not authenticated")
                                        val userId = json.optString("user_id")
                                        val desktopId = json.optString("desktop_device_id")
                                        val secret = json.optString("pairing_secret")
                                        val baseUrl = json.optString("base_url", "http://10.0.2.2:8000")
                                        val mobileId =
                                            "mobile-${android.os.Build.MODEL.hashCode()}-${System.currentTimeMillis()}"

                                        val result = api.consumePairing(
                                            baseUrl = baseUrl,
                                            clerkToken = token,
                                            pairingSecret = secret,
                                            mobileDeviceId = mobileId,
                                            deviceName = "Jarvis ${android.os.Build.MODEL}",
                                        )

                                        sessionStore.savePairingConfig(
                                            userId = userId,
                                            desktopDeviceId = desktopId,
                                            baseUrl = baseUrl,
                                            mobileDeviceId = mobileId,
                                        )
                                        sessionStore.saveDeviceTokens(
                                            accessToken = result.accessToken,
                                            refreshToken = result.refreshToken,
                                            deviceSecret = result.deviceSecret,
                                        )

                                        JarvisForegroundService.start(applicationContext)
                                        screen = AppScreen.CHAT
                                        Toast.makeText(
                                            this@MainActivity,
                                            "Paired successfully",
                                            Toast.LENGTH_SHORT,
                                        ).show()
                                    } catch (e: Exception) {
                                        pairingError = e.message
                                    } finally {
                                        pairingLoading = false
                                    }
                                }
                            },
                            onSkipToChat = { screen = AppScreen.CHAT },
                        )

                        AppScreen.CHAT -> ChatScreen(
                            connected = connected,
                            isSending = isSending,
                            isRecording = isRecording,
                            messages = messages,
                            executions = executions,
                            onOpenSettings = {
                                AccessibilityExecutor.openAccessibilitySettings(this@MainActivity)
                            },
                            onToggleRecord = {
                                if (isRecording) {
                                    val file = audioRecorder?.stop()
                                    isRecording = false
                                    executions.add(
                                        0,
                                        ExecutionCard(
                                            command = "voice",
                                            status = "recorded",
                                            detail = file?.name ?: "audio",
                                        ),
                                    )
                                } else {
                                    audioRecorder?.start()
                                    isRecording = true
                                }
                            },
                            onSend = { text ->
                                scope.launch {
                                    isSending = true
                                    messages.add(ChatBubble(role = "user", content = text))
                                    executions.add(
                                        0,
                                        ExecutionCard(
                                            command = text,
                                            status = "pending",
                                            detail = "Dispatching…",
                                        ),
                                    )
                                    try {
                                        val token = sessionStore.getClerkToken()
                                            ?: throw IllegalStateException("Not signed in")
                                        val baseUrl = sessionStore.getBaseUrl()
                                            ?: throw IllegalStateException("Not paired")
                                        val deviceId = sessionStore.getDeviceId().orEmpty()
                                        val reply = api.postChat(baseUrl, token, text, deviceId)
                                        messages.add(ChatBubble(role = "assistant", content = reply))
                                        if (executions.isNotEmpty()) {
                                            executions[0] = executions[0].copy(
                                                status = "success",
                                                detail = "Completed",
                                            )
                                        }
                                    } catch (e: Exception) {
                                        messages.add(
                                            ChatBubble(
                                                role = "assistant",
                                                content = "Error: ${e.message}",
                                            ),
                                        )
                                        if (executions.isNotEmpty()) {
                                            executions[0] = executions[0].copy(
                                                status = "error",
                                                detail = e.message ?: "failed",
                                            )
                                        }
                                    } finally {
                                        isSending = false
                                    }
                                }
                            },
                        )
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        lifecycleScope.launch {
            if (sessionStore.isPairedFlow.first()) {
                JarvisForegroundService.reconnect()
            }
        }
    }
}
