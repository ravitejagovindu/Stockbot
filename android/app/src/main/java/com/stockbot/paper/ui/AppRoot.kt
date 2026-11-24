package com.stockbot.paper.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.stockbot.paper.BuildConfig
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.theme.StockBotTheme
import com.stockbot.paper.theme.ThemeMode

/** A request to open a tab (debug intent extra). A class, not a data class, so repeating the same tab still counts as new. */
class TabRequest(val tab: Tab)

@Composable
fun AppRoot(vm: PaperViewModel, tabRequest: TabRequest?) {
    val t = StockBotTheme.tokens
    var tab by rememberSaveable { mutableStateOf(Tab.TODAY) }
    LaunchedEffect(tabRequest) { if (tabRequest != null) tab = tabRequest.tab }

    val themeMode by vm.themeMode.collectAsStateWithLifecycle()
    val scenario by vm.scenario.collectAsStateWithLifecycle()
    var debugOpen by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().background(t.background)) {
        TopBar(
            title = tab.title,
            showSampleTag = vm.isSample,
            themeMode = themeMode,
            onTheme = vm::setThemeMode,
            onTitleLongPress = { if (BuildConfig.DEBUG) debugOpen = true },
        )
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (tab) {
                Tab.TODAY -> TodayScreen(vm.today.collectAsStateWithLifecycle().value) { vm.reload(Tab.TODAY) }
                Tab.ACCOUNT -> AccountScreen(vm.account.collectAsStateWithLifecycle().value) { vm.reload(Tab.ACCOUNT) }
                Tab.POSITIONS -> PositionsScreen(vm.positions.collectAsStateWithLifecycle().value) { vm.reload(Tab.POSITIONS) }
                Tab.TRADES -> TradesScreen(vm.trades.collectAsStateWithLifecycle().value) { vm.reload(Tab.TRADES) }
            }
        }
        BottomBar(selected = tab, onSelect = { tab = it })
    }

    if (debugOpen && BuildConfig.DEBUG) {
        ScenarioDialog(current = scenario, onPick = { vm.selectScenario(it); debugOpen = false }, onDismiss = { debugOpen = false })
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TopBar(
    title: String,
    showSampleTag: Boolean,
    themeMode: ThemeMode,
    onTheme: (ThemeMode) -> Unit,
    onTitleLongPress: () -> Unit,
) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    Column(Modifier.fillMaxWidth().statusBarsPadding()) {
        Row(
            Modifier.fillMaxWidth().height(52.dp).padding(horizontal = t.screenPadding),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(title, style = type.title, modifier = Modifier.combinedClickable(onClick = {}, onLongClick = onTitleLongPress))
                if (showSampleTag) SampleTag()
            }
            ThemeMenu(themeMode, onTheme)
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(t.hairline))
    }
}

@Composable
private fun SampleTag() {
    val t = StockBotTheme.tokens
    Text(
        "SAMPLE DATA",
        style = StockBotTheme.type.tag,
        modifier = Modifier
            .clip(RoundedCornerShape(4.dp))
            .background(t.hairline)
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

@Composable
private fun ThemeMenu(mode: ThemeMode, onPick: (ThemeMode) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        Text(
            "Theme: ${mode.label}",
            style = StockBotTheme.type.label,
            modifier = Modifier.clickable { open = true }.padding(vertical = 12.dp, horizontal = 4.dp),
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            ThemeMode.entries.forEach { m ->
                DropdownMenuItem(
                    text = { Text(m.label, fontWeight = if (m == mode) FontWeight.SemiBold else FontWeight.Normal) },
                    onClick = { onPick(m); open = false },
                )
            }
        }
    }
}

@Composable
private fun BottomBar(selected: Tab, onSelect: (Tab) -> Unit) {
    val t = StockBotTheme.tokens
    Column(Modifier.fillMaxWidth().background(t.card).navigationBarsPadding()) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(t.hairline))
        Row(Modifier.fillMaxWidth()) {
            Tab.entries.forEach { tab ->
                val active = tab == selected
                Column(
                    Modifier.weight(1f).clickable { onSelect(tab) },
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Box(Modifier.fillMaxWidth().height(2.dp).background(if (active) t.accent else t.card))
                    Text(
                        tab.title,
                        style = StockBotTheme.type.body.copy(
                            color = if (active) t.accent else t.muted,
                            fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
                        ),
                        modifier = Modifier.padding(vertical = 14.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun ScenarioDialog(current: Scenario, onPick: (Scenario) -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
        title = { Text("Mock scenario") },
        text = {
            Column {
                Scenario.entries.forEach { s ->
                    Row(
                        Modifier.fillMaxWidth().clickable { onPick(s) }.padding(vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = s == current, onClick = { onPick(s) })
                        Column {
                            Text(s.label)
                            Text(s.summary, style = StockBotTheme.type.label)
                        }
                    }
                }
            }
        },
    )
}
