package com.jarvis.omega.network

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

typealias CommandHandler = suspend (JSONObject) -> JSONObject

class JarvisWebSocket(
    private val scope: CoroutineScope,
    private val onConnectionChanged: (Boolean) -> Unit,
    private val commandHandler: CommandHandler,
) {
    private val client = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var reconnectJob: Job? = null
    private val running = AtomicBoolean(false)

  private var lastBaseUrl: String = ""
    private var lastDeviceId: String = ""
    private var lastToken: String = ""

    fun start(baseUrl: String, deviceId: String, clerkToken: String) {
        lastBaseUrl = baseUrl.trimEnd('/')
        lastDeviceId = deviceId
        lastToken = clerkToken
        running.set(true)
        connect()
    }

    fun stop() {
        running.set(false)
        reconnectJob?.cancel()
        webSocket?.close(1000, "client_stop")
        webSocket = null
        onConnectionChanged(false)
    }

    fun sendNotification(pkg: String, title: String, text: String) {
        val payload = JSONObject()
            .put("type", "NOTIFICATION")
            .put("device_id", lastDeviceId)
            .put(
                "payload",
                JSONObject()
                    .put("pkg", pkg)
                    .put("title", title)
                    .put("text", text)
                    .put("timestamp", System.currentTimeMillis()),
            )
        webSocket?.send(payload.toString())
    }

    private fun connect() {
        if (!running.get()) return
        val wsBase = lastBaseUrl.replace("^http".toRegex(RegexOption.IGNORE_CASE), "ws")
        val url = "$wsBase/ws/$lastDeviceId?token=${lastToken}"
        val request = Request.Builder().url(url).build()

        webSocket = client.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    Log.i(TAG, "WebSocket connected")
                    onConnectionChanged(true)
                    webSocket.send(
                        JSONObject()
                            .put("type", "HEARTBEAT")
                            .put("payload", JSONObject().put("status", "alive"))
                            .toString(),
                    )
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    scope.launch(Dispatchers.Default) {
                        handleMessage(webSocket, text)
                    }
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(1000, null)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    Log.w(TAG, "WebSocket closed: $reason")
                    onConnectionChanged(false)
                    scheduleReconnect()
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    Log.e(TAG, "WebSocket failure", t)
                    onConnectionChanged(false)
                    scheduleReconnect()
                }
            },
        )
    }

    private fun scheduleReconnect() {
        if (!running.get()) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            delay(4000)
            if (running.get()) connect()
        }
    }

    private suspend fun handleMessage(socket: WebSocket, text: String) {
        val msg = runCatching { JSONObject(text) }.getOrNull() ?: return
        val type = msg.optString("type")
        if (type.equals("HEARTBEAT", ignoreCase = true)) {
            socket.send(
                JSONObject()
                    .put("type", "HEARTBEAT")
                    .put("payload", JSONObject().put("status", "alive"))
                    .toString(),
            )
            return
        }
        if (type.equals("COMMAND", ignoreCase = true)) {
            val correlationId = msg.optString("correlation_id")
            val payload = msg.optJSONObject("payload") ?: JSONObject()
            val resultPayload = runCatching { commandHandler(payload) }.getOrElse { err ->
                JSONObject().put("ok", false).put("error", err.message ?: "execution_failed")
            }
            val envelope = JSONObject()
                .put("type", "RESULT")
                .put("device_id", lastDeviceId)
                .put("correlation_id", correlationId)
                .put("payload", resultPayload)
            socket.send(envelope.toString())
        }
    }

    companion object {
        private const val TAG = "JarvisWebSocket"
    }
}
