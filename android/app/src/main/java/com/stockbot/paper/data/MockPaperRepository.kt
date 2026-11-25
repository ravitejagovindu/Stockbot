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

    private val _jobScenario = MutableStateFlow(JobScenario.DONE)
    val jobScenario: StateFlow<JobScenario> = _jobScenario

    fun selectJob(s: JobScenario) {
        _jobScenario.value = s
    }

    override val isSample: Boolean = true

    override suspend fun getToday(): Loaded<TodayState> = load("today", Contract::today)
    override suspend fun getAccount(): Loaded<AccountSnapshot> = load("account", Contract::account)
    override suspend fun getPositions(): Loaded<PositionsState> = load("positions", Contract::positions)
    override suspend fun getTrades(): Loaded<TradesState> = load("trades", Contract::trades)

    override suspend fun getJob(): Loaded<JobStatus> {
        if (latencyMs > 0) delay(latencyMs)
        if (_scenario.value == Scenario.ERROR) throw Contract.error(source.read("error_${Scenario.ERROR.fileSuffix}.json"))
        return Loaded(Contract.job(source.read(_jobScenario.value.file)))
    }

    private suspend fun <T> load(kind: String, parse: (String) -> T): Loaded<T> {
        if (latencyMs > 0) delay(latencyMs)
        val scenario = _scenario.value
        if (scenario == Scenario.ERROR) throw Contract.error(source.read("error_${scenario.fileSuffix}.json"))
        return Loaded(parse(source.read("${kind}_${scenario.fileSuffix}.json")))
    }
}
