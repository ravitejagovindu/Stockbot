package com.stockbot.paper.data

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Where the example JSON files come from: the app's assets on the phone, the class path in unit tests. */
fun interface ExampleSource {
    /** The text of docs/android/contract/examples/[name]. */
    fun read(name: String): String
}

/**
 * Stage 1 and 2 data: the example JSON files of the contract, parsed exactly as the real responses will be.
 * The scenario can be switched at any time; screens reload when it changes. [latencyMs] makes the loading state visible.
 */
class MockPaperRepository(
    private val source: ExampleSource,
    initial: Scenario = Scenario.EMPTY,
    private val latencyMs: Long = 450,
) : PaperRepository {

    private val _scenario = MutableStateFlow(initial)
    val scenario: StateFlow<Scenario> = _scenario

    fun select(scenario: Scenario) {
        _scenario.value = scenario
    }

    override val isSample: Boolean = true

    override suspend fun getToday(): TodayState = load("today", Contract::today)
    override suspend fun getAccount(): AccountSnapshot = load("account", Contract::account)
    override suspend fun getPositions(): PositionsState = load("positions", Contract::positions)
    override suspend fun getTrades(): TradesState = load("trades", Contract::trades)

    private suspend fun <T> load(kind: String, parse: (String) -> T): T {
        if (latencyMs > 0) delay(latencyMs)
        val scenario = _scenario.value
        if (scenario == Scenario.ERROR) throw Contract.error(source.read("error_${scenario.fileSuffix}.json"))
        return parse(source.read("${kind}_${scenario.fileSuffix}.json"))
    }
}
