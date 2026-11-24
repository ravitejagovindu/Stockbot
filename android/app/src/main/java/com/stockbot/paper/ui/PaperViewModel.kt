package com.stockbot.paper.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.stockbot.paper.data.AccountSnapshot
import com.stockbot.paper.data.MockPaperRepository
import com.stockbot.paper.data.PositionsState
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.data.TodayState
import com.stockbot.paper.data.TradesState
import com.stockbot.paper.theme.ThemeMode
import com.stockbot.paper.theme.ThemeModeStore
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

enum class Tab(val title: String) { TODAY("Today"), ACCOUNT("Account"), POSITIONS("Positions"), TRADES("Trades") }

/** Holds the four screen states and the theme override. The scenario switch is a debug feature of the mock repository. */
class PaperViewModel(
    private val repo: MockPaperRepository,
    private val themeStore: ThemeModeStore,
) : ViewModel() {
    private val loader = ScreenLoader(repo)

    val isSample: Boolean = repo.isSample
    val scenario: StateFlow<Scenario> = repo.scenario

    private val _today = MutableStateFlow<ScreenState<TodayState>>(ScreenState.Loading)
    private val _account = MutableStateFlow<ScreenState<AccountSnapshot>>(ScreenState.Loading)
    private val _positions = MutableStateFlow<ScreenState<PositionsState>>(ScreenState.Loading)
    private val _trades = MutableStateFlow<ScreenState<TradesState>>(ScreenState.Loading)
    val today: StateFlow<ScreenState<TodayState>> = _today
    val account: StateFlow<ScreenState<AccountSnapshot>> = _account
    val positions: StateFlow<ScreenState<PositionsState>> = _positions
    val trades: StateFlow<ScreenState<TradesState>> = _trades

    private val jobs = HashMap<Tab, Job>()

    val themeMode: StateFlow<ThemeMode> = themeStore.mode.stateIn(viewModelScope, SharingStarted.Eagerly, ThemeMode.SYSTEM)

    init {
        Tab.entries.forEach { reload(it) }
    }

    fun reload(tab: Tab) {
        jobs[tab]?.cancel()
        jobs[tab] = viewModelScope.launch {
            when (tab) {
                Tab.TODAY -> { _today.value = ScreenState.Loading; _today.value = loader.today() }
                Tab.ACCOUNT -> { _account.value = ScreenState.Loading; _account.value = loader.account() }
                Tab.POSITIONS -> { _positions.value = ScreenState.Loading; _positions.value = loader.positions() }
                Tab.TRADES -> { _trades.value = ScreenState.Loading; _trades.value = loader.trades() }
            }
        }
    }

    fun selectScenario(s: Scenario) {
        repo.select(s)
        Tab.entries.forEach { reload(it) }
    }

    fun setThemeMode(mode: ThemeMode) {
        viewModelScope.launch { themeStore.set(mode) }
    }
}
