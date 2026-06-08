package com.jarvis.omega.actions

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import java.util.ArrayDeque

object AccessibilityExecutor {

    fun execute(service: AccessibilityService, payload: JSONObject): JSONObject {
        val cmd = payload.optString("cmd", payload.optString("command", ""))
        return when (cmd) {
            "tap" -> tap(service, payload.optDouble("x").toFloat(), payload.optDouble("y").toFloat())
            "type" -> type(service, payload.optString("text"))
            "back" -> navigate(service, AccessibilityService.GLOBAL_ACTION_BACK)
            "home" -> navigate(service, AccessibilityService.GLOBAL_ACTION_HOME)
            "screenshot" -> screenshot(service)
            "open_app" -> openApp(service, payload.optString("pkg", payload.optString("package")))
            "android_whatsapp_send" -> whatsappSend(
                service,
                payload.optString("contact"),
                payload.optString("text"),
            )
            "android_sms_send" -> smsSend(
                service,
                payload.optString("number", payload.optString("contact")),
                payload.optString("text"),
            )
            "call" -> call(service, payload.optString("target", payload.optString("number")))
            else -> JSONObject().put("ok", false).put("error", "Unknown command: $cmd")
        }
    }

    private fun tap(service: AccessibilityService, x: Float, y: Float): JSONObject {
        if (x <= 0f || y <= 0f) {
            return JSONObject().put("ok", false).put("error", "Invalid coordinates")
        }
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 50)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        val ok = service.dispatchGesture(gesture, null, null)
        return JSONObject().put("ok", ok).put("data", JSONObject().put("x", x).put("y", y))
    }

    private fun type(service: AccessibilityService, text: String): JSONObject {
        val root = service.rootInActiveWindow ?: return fail("No active window")
        val focused = findFocusedEditable(root) ?: findFirstEditable(root)
        if (focused == null) return fail("No editable field found")
        val args = Bundle()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        val ok = focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        return JSONObject().put("ok", ok).put("data", JSONObject().put("text", text))
    }

    private fun navigate(service: AccessibilityService, action: Int): JSONObject {
        val ok = service.performGlobalAction(action)
        return JSONObject().put("ok", ok)
    }

    private fun screenshot(service: AccessibilityService): JSONObject {
        return try {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
                var success = false
                service.takeScreenshot(
                    android.view.Display.DEFAULT_DISPLAY,
                    service.mainExecutor,
                    object : AccessibilityService.TakeScreenshotCallback {
                        override fun onSuccess(result: AccessibilityService.ScreenshotResult) {
                            success = true
                            result.hardwareBuffer.close()
                        }
                        override fun onFailure(errorCode: Int) {
                            success = false
                        }
                    },
                )
                JSONObject().put("ok", success).put("data", JSONObject().put("message", "Screenshot requested"))
            } else {
                JSONObject().put("ok", false).put("error", "Screenshot requires Android 11+")
            }
        } catch (e: Exception) {
            fail(e.message ?: "screenshot_failed")
        }
    }

    private fun openApp(service: AccessibilityService, pkg: String): JSONObject {
        if (pkg.isBlank()) return fail("Package name required")
        val pm = service.packageManager
        val launch = pm.getLaunchIntentForPackage(pkg)
            ?: return fail("App not installed: $pkg")
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        service.startActivity(launch)
        return JSONObject().put("ok", true).put("data", JSONObject().put("pkg", pkg))
    }

    private fun whatsappSend(service: AccessibilityService, contact: String, text: String): JSONObject {
        val uri = Uri.parse("https://wa.me/?text=${Uri.encode(text)}")
        val intent = Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        service.startActivity(intent)
        return JSONObject()
            .put("ok", true)
            .put("data", JSONObject().put("contact", contact).put("text", text).put("note", "Opened WhatsApp"))
    }

    private fun smsSend(service: AccessibilityService, number: String, text: String): JSONObject {
        val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$number"))
            .putExtra("sms_body", text)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        service.startActivity(intent)
        return JSONObject().put("ok", true).put("data", JSONObject().put("number", number))
    }

    private fun call(service: AccessibilityService, target: String): JSONObject {
        val intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:$target"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        service.startActivity(intent)
        return JSONObject().put("ok", true).put("data", JSONObject().put("target", target))
    }

    fun findNodeByTextBfs(root: AccessibilityNodeInfo, text: String): AccessibilityNodeInfo? {
        val q = ArrayDeque<AccessibilityNodeInfo>()
        q.add(root)
        val needle = text.lowercase()
        while (q.isNotEmpty()) {
            val node = q.removeFirst()
            val nodeText = buildString {
                node.text?.let { append(it) }
                node.contentDescription?.let { append(it) }
            }.lowercase()
            if (needle in nodeText) return node
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let { q.add(it) }
            }
        }
        return null
    }

    fun nodeBounds(node: AccessibilityNodeInfo): Rect {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        return rect
    }

    private fun findFocusedEditable(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (root.isFocused && root.isEditable) return root
        for (i in 0 until root.childCount) {
            val child = root.getChild(i) ?: continue
            val found = findFocusedEditable(child)
            if (found != null) return found
        }
        return null
    }

    private fun findFirstEditable(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val q = ArrayDeque<AccessibilityNodeInfo>()
        q.add(root)
        while (q.isNotEmpty()) {
            val node = q.removeFirst()
            if (node.isEditable) return node
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let { q.add(it) }
            }
        }
        return null
    }

    private fun fail(message: String): JSONObject =
        JSONObject().put("ok", false).put("error", message)

    fun openAccessibilitySettings(context: android.content.Context) {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun openNotificationSettings(context: android.content.Context) {
        context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
