package com.jarvis.omega.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

@Composable
fun AuthScreen(
    onTokenSaved: (String) -> Unit,
) {
    val token = remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Jarvis Mobile", style = androidx.compose.material3.MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(8.dp))
        Text(
            "Paste your Clerk session JWT from the web dashboard (or sign in via Clerk in browser and copy the Bearer token).",
            style = androidx.compose.material3.MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(16.dp))
        OutlinedTextField(
            value = token.value,
            onValueChange = { token.value = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Clerk JWT") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = false,
            minLines = 3,
        )
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = { onTokenSaved(token.value.trim()) },
            modifier = Modifier.fillMaxWidth(),
            enabled = token.value.isNotBlank(),
        ) {
            Text("Continue")
        }
    }
}
