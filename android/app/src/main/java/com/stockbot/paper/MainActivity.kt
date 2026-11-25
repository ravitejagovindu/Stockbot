package com.stockbot.paper

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStore
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.stockbot.paper.data.ExampleSource
import com.stockbot.paper.net.ConnectionStore
import com.stockbot.paper.net.ConnectionTester
import com.stockbot.paper.net.FileResponseCache
import com.stockbot.paper.net.KeystoreSecretBox
import com.stockbot.paper.net.NetworkPaperRepository
import com.stockbot.paper.net.UrlConnectionTransport
import java.io.File
import com.stockbot.paper.data.MockPaperRepository
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.theme.StockBotTheme
import com.stockbot.paper.theme.ThemeMode
import com.stockbot.paper.theme.ThemeModeStore
import com.stockbot.paper.theme.resolveDark
import com.stockbot.paper.ui.AppRoot
import com.stockbot.paper.ui.PaperViewModel
import com.stockbot.paper.ui.Tab
import com.stockbot.paper.ui.TabRequest

private val Context.settingsDataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

class MainActivity : ComponentActivity() {
    private var tabRequest by mutableStateOf<TabRequest?>(null)
    private var viewModel: PaperViewModel? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val vm: PaperViewModel = viewModel(
                factory = viewModelFactory {
                    initializer {
                        val ctx = applicationContext
                        val source = ExampleSource { name -> ctx.assets.open("contract-examples/$name").bufferedReader().use { it.readText() } }
                        val cache = FileResponseCache(File(ctx.filesDir, "last_good"))
                        PaperViewModel(
                            MockPaperRepository(source),
                            PaperViewModel.NetworkPaperRepositoryFactory { endpoint -> NetworkPaperRepository(endpoint, UrlConnectionTransport(), cache) },
                            ThemeModeStore(ctx.settingsDataStore),
                            ConnectionStore(ctx.settingsDataStore, KeystoreSecretBox()),
                            ConnectionTester(UrlConnectionTransport()),
                        )
                    }
                },
            )
            viewModel = vm
            LaunchedEffect(Unit) { applyDebugExtras(intent) }
            val mode by vm.themeMode.collectAsStateWithLifecycle()
            val dark = mode.resolveDark()
            val activity = this@MainActivity
            DisposableEffect(dark) {
                val style = if (dark) SystemBarStyle.dark(Color.TRANSPARENT) else SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
                activity.enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
                onDispose {}
            }
            StockBotTheme(mode) { AppRoot(vm, tabRequest) }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        applyDebugExtras(intent)
    }

    /**
     * Debug builds only: `adb shell am start -n com.stockbot.paper/.MainActivity --es scenario SIGNAL_DAY --es theme DARK --es tab ACCOUNT`.
     * Used to take screenshots. With `--es server http://<address>:8765 --es token <token>` the connection is set up without typing (and the sample data is turned off);
     * those two extras are read once and removed from the intent at once. Release builds ignore all of these extras.
     */
    private fun applyDebugExtras(intent: Intent?) {
        if (!BuildConfig.DEBUG || intent == null) return
        val vm = viewModel
        intent.getStringExtra("scenario")?.let { s ->
            Scenario.entries.firstOrNull { it.name == s }?.let { vm?.selectScenario(it) }
        }
        intent.getStringExtra("theme")?.let { vm?.setThemeMode(ThemeMode.parse(it)) }
        intent.getStringExtra("tab")?.let { s -> Tab.entries.firstOrNull { it.name == s }?.let { tabRequest = TabRequest(it) } }
        intent.getStringExtra("jobscenario")?.let { s ->
            com.stockbot.paper.data.JobScenario.entries.firstOrNull { it.name == s }?.let { vm?.selectJobScenario(it) }
        }
        val server = intent.getStringExtra("server")
        val token = intent.getStringExtra("token")
        if (server != null || token != null) vm?.applyDebugConnection(server, token)
        intent.removeExtra("jobscenario"); intent.removeExtra("scenario"); intent.removeExtra("theme"); intent.removeExtra("tab"); intent.removeExtra("server"); intent.removeExtra("token")
    }
}
