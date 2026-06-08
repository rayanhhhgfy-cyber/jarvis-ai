package com.jarvis.omega.actions

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.jarvis.omega.service.JarvisForegroundService

class JarvisNotificationListenerService : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn ?: return
        val extras = sbn.notification.extras
        val title = extras.getCharSequence("android.title")?.toString().orEmpty()
        val text = extras.getCharSequence("android.text")?.toString().orEmpty()
        val pkg = sbn.packageName.orEmpty()
        JarvisForegroundService.notifyFromSystem(pkg, title, text)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
    }
}
