package com.jarvis.omega.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.jarvis.omega.actions.AccessibilityExecutor

data class ChatBubble(
    val id: String = java.util.UUID.randomUUID().toString(),
    val role: String,
    val content: String,
    val timestamp: Long = System.currentTimeMillis(),
)

data class ExecutionCard(
    val id: String = java.util.UUID.randomUUID().toString(),
    val command: String,
    val status: String,
    val detail: String,
)

@Composable
fun ChatScreen(
    connected: Boolean,
    isSending: Boolean,
    onSend: (String) -> Unit,
    onToggleRecord: () -> Unit,
    isRecording: Boolean,
    onOpenSettings: () -> Unit,
    messages: List<ChatBubble>,
    executions: List<ExecutionCard>,
) {
    val input = remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF020617))
            .padding(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("Jarvis", style = androidx.compose.material3.MaterialTheme.typography.titleLarge)
                Text(
                    if (connected) "Online" else "Offline",
                    color = if (connected) Color(0xFF34D399) else Color(0xFFF87171),
                )
            }
            IconButton(onClick = onOpenSettings) {
                Icon(Icons.Default.Settings, contentDescription = "Settings")
            }
        }

        if (executions.isNotEmpty()) {
            Text("Recent commands", modifier = Modifier.padding(vertical = 4.dp))
            LazyColumn(modifier = Modifier.height(100.dp)) {
                items(executions.takeLast(5)) { card ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 2.dp),
                        colors = CardDefaults.cardColors(containerColor = Color(0xFF0F172A)),
                    ) {
                        Column(Modifier.padding(8.dp)) {
                            Text(card.command, color = Color.White)
                            Text("${card.status} — ${card.detail}", color = Color(0xFF94A3B8))
                        }
                    }
                }
            }
        }

        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            reverseLayout = true,
        ) {
            items(messages.reversed()) { msg ->
                val align = if (msg.role == "user") Arrangement.End else Arrangement.Start
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    horizontalArrangement = align,
                ) {
                    Text(
                        msg.content,
                        modifier = Modifier
                            .background(
                                if (msg.role == "user") Color(0xFF0369A1) else Color(0xFF1E293B),
                                RoundedCornerShape(12.dp),
                            )
                            .padding(12.dp),
                        color = Color.White,
                    )
                }
            }
        }

        if (isSending) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                CircularProgressIndicator()
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onToggleRecord) {
                Icon(
                    if (isRecording) Icons.Default.MicOff else Icons.Default.Mic,
                    contentDescription = "Record",
                    tint = if (isRecording) Color(0xFFF87171) else Color(0xFF38BDF8),
                )
            }
            OutlinedTextField(
                value = input.value,
                onValueChange = { input.value = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Ask Jarvis…") },
                maxLines = 4,
            )
            IconButton(
                onClick = {
                    val text = input.value.trim()
                    if (text.isNotEmpty()) {
                        onSend(text)
                        input.value = ""
                    }
                },
                enabled = !isSending && input.value.isNotBlank(),
            ) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
            }
        }
    }
}

@Composable
fun PermissionsBanner(onEnableAccessibility: () -> Unit, onEnableNotifications: () -> Unit) {
    if (!com.jarvis.omega.actions.JarvisAccessibilityService.isEnabled()) {
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
            colors = CardDefaults.cardColors(containerColor = Color(0xFF451A03)),
        ) {
            Column(Modifier.padding(12.dp)) {
                Text("Accessibility required for automation")
                Spacer(Modifier.height(8.dp))
                androidx.compose.material3.Button(onClick = onEnableAccessibility) {
                    Text("Enable Accessibility")
                }
                Spacer(Modifier.height(4.dp))
                androidx.compose.material3.OutlinedButton(onClick = onEnableNotifications) {
                    Text("Notification access")
                }
            }
        }
    }
}
