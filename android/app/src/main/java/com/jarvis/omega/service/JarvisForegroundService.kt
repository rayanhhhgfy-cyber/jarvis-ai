package com.jarvis.omega.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.jarvis.omega.MainActivity
import com.jarvis.omega.R
import com.jarvis.omega.actions.AccessibilityExecutor
import com.jarvis.omega.actions.JarvisAccessibilityService
import com.jarvis.omega.data.SessionStore
import com.jarvis.omega.network.JarvisWebSocket
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.json.JSONObject

class JarvisForegroundService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var sessionStore: SessionStore
    private var webSocket: JarvisWebSocket? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        sessionStore = SessionStore(applicationContext)
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification(connected = false))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_START, null -> connectIfReady()
        }
        return START_STICKY
    }

    private fun connectIfReady() {
        val baseUrl = sessionStore.getBaseUrl()
        val deviceId = sessionStore.getDeviceId()
        val clerkToken = sessionStore.getClerkToken()
        if (baseUrl.isNullOrBlank() || deviceId.isNullOrBlank() || clerkToken.isNullOrBlank()) {
            updateNotification(false)
            return
        }

        webSocket?.stop()
        webSocket = JarvisWebSocket(
            scope = scope,
            onConnectionChanged = { connected -> updateNotification(connected) },
            commandHandler = { payload ->
                val service = JarvisAccessibilityService.instance
                if (service == null) {
                    JSONObject().put("ok", false).put("error", "Accessibility service not enabled")
                } else {
                    AccessibilityExecutor.execute(service, payload)
                }
            },
        ).also { it.start(baseUrl, deviceId, clerkToken) }
    }

    private fun updateNotification(connected: Boolean) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIFICATION_ID, buildNotification(connected))
    }

    private fun buildNotification(connected: Boolean): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val status = if (connected) "Connected to Jarvis server" else "Connecting…"
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.foreground_notification_title))
            .setContentText(status)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.foreground_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.foreground_channel_desc)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    override fun onDestroy() {
        webSocket?.stop()
        scope.cancel()
        instance = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_START = "com.jarvis.omega.START"
        const val ACTION_STOP = "com.jarvis.omega.STOP"
        private const val CHANNEL_ID = "jarvis_connection"
        private const val NOTIFICATION_ID = 1001

        @Volatile
        private var instance: JarvisForegroundService? = null

        fun start(context: Context) {
            val intent = Intent(context, JarvisForegroundService::class.java).apply {
                action = ACTION_START
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, JarvisForegroundService::class.java))
        }

        fun notifyFromSystem(pkg: String, title: String, text: String) {
            instance?.webSocket?.sendNotification(pkg, title, text)
        }

        fun reconnect() {
            instance?.connectIfReady()
        }
    }
}
