package com.stockbot.paper.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.stockbot.paper.data.AccountSnapshot
import com.stockbot.paper.data.JobScenario
import com.stockbot.paper.data.JobStatus
import com.stockbot.paper.data.Loaded
import com.stockbot.paper.data.MockPaperRepository
import com.stockbot.paper.data.PaperRepository
import com.stockbot.paper.data.PositionsState
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.data.TodayState
import com.stockbot.paper.data.TradesState
import com.stockbot.paper.net.ConnectionSettings
import com.stockbot.paper.net.ConnectionStore
import com.stockbot.paper.net.ConnectionTester
import com.stockbot.paper.net.Endpoint
import com.stockbot.paper.net.NetworkPaperRepository
import com.stockbot.paper.net.SecretText
import com.stockbot.paper.net.TestResult
import com.stockbot.paper.net.DEFAULT_SERVER
import com.stockbot.paper.net.normalizeAddress
import com.stockbot.paper.theme.ThemeMode
import com.stockbot.paper.theme.ThemeModeStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Tab(val title: String) { TODAY("Today"), ACCOUNT("Account"), POSITIONS("Positions"), TRADES("Trades"), JOB("Job") }

/** Sends each call to the sample data or to the laptop, depending on the Connection screen's switch. */
class AppRepository(private val mock: PaperRepository, private val network: PaperRepository) : PaperRepository {
    @Volatile var useSample: Boolean = true
    private val current: PaperRepository get() = if (useSample) mock else network

    override val isSample: Boolean get() = useSample
    override suspend fun getToday(): Loaded<TodayState> = current.getToday()
    override suspend fun getAccount(): Loaded<AccountSnapshot> = current.getAccount()
    override suspend fun getPositions(): Loaded<PositionsState> = current.getPositions()
    override suspend fun getTrades(): Loaded<TradesState> = current.getTrades()
    override suspend fun getJob(): Loaded<JobStatus> = current.getJob()
}

/** Holds the four screen states, the theme override and the connection settings. The scenario switch is a debug feature of the mock repository. */
class PaperViewModel(
    private val mock: MockPaperRepository,
    private val network: NetworkPaperRepositoryFactory,
    private val themeStore: ThemeModeStore,
    private val connectionStore: ConnectionStore,
    private val tester: ConnectionTester,
) : ViewModel() {
    /** Builds the network repository around a function that returns the current endpoint (the VM owns the settings). */
    fun interface NetworkPaperRepositoryFactory {
        fun create(endpoint: () -> Endpoint?): NetworkPaperRepository
    }

    @Volatile private var settingsNow = ConnectionSettings()
    private val repo = AppRepository(mock, network.create { settingsNow.token?.takeIf { settingsNow.hasToken }?.let { Endpoint(settingsNow.address, it) } })
    private val loader = ScreenLoader(repo)

    private val _connection = MutableStateFlow(settingsNow)
    val connection: StateFlow<ConnectionSettings> = _connection
    val isSample: StateFlow<Boolean> = _connection.map { it.useSample }.stateIn(viewModelScope, SharingStarted.Eagerly, true)
    val scenario: StateFlow<Scenario> = mock.scenario

    private val _today = MutableStateFlow<ScreenState<TodayState>>(ScreenState.Loading)
    private val _account = MutableStateFlow<ScreenState<AccountSnapshot>>(ScreenState.Loading)
    private val _positions = MutableStateFlow<ScreenState<PositionsState>>(ScreenState.Loading)
    private val _trades = MutableStateFlow<ScreenState<TradesState>>(ScreenState.Loading)
    private val _job = MutableStateFlow<ScreenState<JobStatus>>(ScreenState.Loading)
    val today: StateFlow<ScreenState<TodayState>> = _today
    val account: StateFlow<ScreenState<AccountSnapshot>> = _account
    val positions: StateFlow<ScreenState<PositionsState>> = _positions
    val trades: StateFlow<ScreenState<TradesState>> = _trades
    val job: StateFlow<ScreenState<JobStatus>> = _job
    val jobScenario: StateFlow<JobScenario> = mock.jobScenario

    private val _refreshing = MutableStateFlow<Set<Tab>>(emptySet())
    /** The tabs whose pull-to-refresh spinner is showing. */
    val refreshing: StateFlow<Set<Tab>> = _refreshing

    private val _testResult = MutableStateFlow<TestResult?>(null)
    val testResult: StateFlow<TestResult?> = _testResult
    private val _testing = MutableStateFlow(false)
    val testing: StateFlow<Boolean> = _testing

    private val jobs = HashMap<Tab, Job>()

    val themeMode: StateFlow<ThemeMode> = themeStore.mode.stateIn(viewModelScope, SharingStarted.Eagerly, ThemeMode.SYSTEM)

    init {
        // The first emission is the stored settings: load the screens with them. Later emissions (a changed address, token or switch) reload.
        viewModelScope.launch {
            var first = true
            connectionStore.settings.collect { s ->
                val changed = s != settingsNow
                settingsNow = s
                repo.useSample = s.useSample
                _connection.value = s
                if (first || changed) Tab.entries.forEach { reload(it) }
                first = false
            }
        }
    }

    /** Loads a tab. A [silent] load (pull-to-refresh, return to the app) keeps the current content on screen and shows the spinner instead of the loading block. */
    fun reload(tab: Tab, silent: Boolean = false) {
        jobs[tab]?.cancel()
        jobs[tab] = viewModelScope.launch {
            if (silent) _refreshing.value = _refreshing.value + tab
            try {
                when (tab) {
                    Tab.TODAY -> { if (!silent) _today.value = ScreenState.Loading; _today.value = loader.today() }
                    Tab.ACCOUNT -> { if (!silent) _account.value = ScreenState.Loading; _account.value = loader.account() }
                    Tab.POSITIONS -> { if (!silent) _positions.value = ScreenState.Loading; _positions.value = loader.positions() }
                    Tab.TRADES -> { if (!silent) _trades.value = ScreenState.Loading; _trades.value = loader.trades() }
                    Tab.JOB -> { if (!silent) _job.value = ScreenState.Loading; _job.value = loader.job() }
                }
            } finally {
                _refreshing.value = _refreshing.value - tab
            }
        }
    }

    /** Pull-to-refresh, and the refresh when the app comes back to the front. */
    fun refresh(tab: Tab) = reload(tab, silent = true)

    fun refreshAll() = Tab.entries.forEach { refresh(it) }

    fun selectScenario(s: Scenario) {
        mock.select(s)
        viewModelScope.launch {
            connectionStore.setUseSample(true)           // a scenario only means something for the sample data
            Tab.entries.forEach { reload(it) }
        }
    }

    /** Debug menu: which job status the sample data shows. */
    fun selectJobScenario(s: JobScenario) {
        mock.selectJob(s)
        viewModelScope.launch {
            connectionStore.setUseSample(true)
            reload(Tab.JOB)
        }
    }

    fun setThemeMode(mode: ThemeMode) {
        viewModelScope.launch { themeStore.set(mode) }
    }

    // ------------------------------------------------------------------------------------------------------------------ Connection screen
    fun setUseSample(value: Boolean) {
        viewModelScope.launch { connectionStore.setUseSample(value) }
    }

    /** Saves the address and, when typed, the token; then calls /v1/health once and shows one line. An empty token field keeps the stored token. */
    fun saveAndTest(addressInput: String, tokenInput: String) {
        viewModelScope.launch {
            _testing.value = true
            _testResult.value = null
            val address = normalizeAddress(addressInput)
            if (address == null) {
                _testResult.value = TestResult.BadAddress
            } else {
                val typed = tokenInput.trim().takeIf { it.isNotEmpty() }?.let(::SecretText)
                connectionStore.save(address, typed)
                val token = typed ?: connectionStore.current().token
                _testResult.value = withContext(Dispatchers.IO) { tester.test(address, token) }
            }
            _testing.value = false
        }
    }

    fun clearTestResult() {
        _testResult.value = null
    }

    /** Debug builds only (the caller checks): set the address and token from an intent so the owner never types them, and turn the sample data off. */
    fun applyDebugConnection(server: String?, token: String?) {
        viewModelScope.launch {
            connectionStore.save(normalizeAddress(server ?: "") ?: DEFAULT_SERVER, token?.takeIf { it.isNotBlank() }?.let(::SecretText))
            connectionStore.setUseSample(false)
        }
    }
}
