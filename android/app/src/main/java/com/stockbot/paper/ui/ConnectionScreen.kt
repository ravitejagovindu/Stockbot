package com.stockbot.paper.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.stockbot.paper.net.TestResult
import com.stockbot.paper.theme.StockBotTheme

/** The Connection screen: where the laptop is, the token, a test, and the switch between the sample data and the real figures. */
@Composable
fun ConnectionScreen(vm: PaperViewModel, onDone: () -> Unit) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    val settings by vm.connection.collectAsStateWithLifecycle()
    val result by vm.testResult.collectAsStateWithLifecycle()
    val testing by vm.testing.collectAsStateWithLifecycle()
    var address by remember(settings.address) { mutableStateOf(settings.address) }
    var token by remember { mutableStateOf("") }                         // never saved with the screen state; cleared as soon as it is stored

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = t.screenPadding, vertical = t.gap), verticalArrangement = Arrangement.spacedBy(t.gap)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("Connection", style = type.headline)
            TextButton(onClick = { vm.clearTestResult(); onDone() }) { Text("Done", style = type.bodyStrong.copy(color = t.accent)) }
        }

        PaperCard {
            Text("Your laptop", style = type.label)
            Field("Server address", address, { address = it }, "http://100.125.195.111:8765", KeyboardType.Uri, secret = false)
            Field(
                "Token", token, { token = it },
                if (settings.hasToken) "Saved. Leave empty to keep it." else "Paste the token",
                KeyboardType.Password, secret = true,
            )
            Button(
                onClick = { vm.saveAndTest(address, token); token = "" },
                enabled = !testing,
                shape = RoundedCornerShape(t.cardCorner),
                colors = ButtonDefaults.buttonColors(containerColor = t.accent, contentColor = if (t.isDark) Color(0xFF0E1116) else Color.White),
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            ) { Text(if (testing) "Testing" else "Test connection") }
            result?.let { Text(it.line, style = type.body.copy(color = resultColor(it)), modifier = Modifier.padding(top = 10.dp)) }
        }

        PaperCard {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f).padding(end = 12.dp)) {
                    Text("Use sample data", style = type.bodyStrong)
                    Text("Made-up figures. Turn it off to see your laptop's data.", style = type.label)
                }
                Switch(
                    checked = settings.useSample,
                    onCheckedChange = vm::setUseSample,
                    colors = SwitchDefaults.colors(checkedTrackColor = t.accent, checkedThumbColor = t.card, uncheckedTrackColor = t.hairline, uncheckedBorderColor = t.muted),
                )
            }
        }

        Text("Read-only. The token stays on this phone, encrypted.", style = type.label, modifier = Modifier.padding(horizontal = 4.dp))
    }
}

@Composable
private fun resultColor(r: TestResult): Color {
    val t = StockBotTheme.tokens
    return if (r is TestResult.Connected) t.gain else t.loss
}

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit, placeholder: String, keyboard: KeyboardType, secret: Boolean) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    Text(label, style = type.label, modifier = Modifier.padding(top = 12.dp, bottom = 4.dp))
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        singleLine = true,
        placeholder = { Text(placeholder, style = type.body.copy(color = t.muted)) },
        textStyle = type.body,
        visualTransformation = if (secret) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        keyboardOptions = KeyboardOptions(keyboardType = keyboard),
        shape = RoundedCornerShape(t.cardCorner),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = t.accent, unfocusedBorderColor = t.hairline, cursorColor = t.accent,
            focusedTextColor = t.text, unfocusedTextColor = t.text, focusedContainerColor = t.card, unfocusedContainerColor = t.card,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}
