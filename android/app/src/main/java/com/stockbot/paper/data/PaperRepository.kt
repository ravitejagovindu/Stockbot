package com.stockbot.paper.data

/** A loaded response. [offlineGeneratedAt] is set when the data is the last good copy kept on the phone because the laptop could not be reached. */
data class Loaded<T>(val data: T, val offlineGeneratedAt: String? = null)

/**
 * What the UI knows about the data. One call per screen; any call may throw, and the UI shows a calm error with Retry.
 * Implementations: [MockPaperRepository] (the contract's example files) and the network repository (the BFF over Tailscale).
 */
interface PaperRepository {
    /** True while the data is made up. Drives the "SAMPLE DATA" tag. */
    val isSample: Boolean

    suspend fun getToday(): Loaded<TodayState>
    suspend fun getAccount(): Loaded<AccountSnapshot>
    suspend fun getPositions(): Loaded<PositionsState>
    suspend fun getTrades(): Loaded<TradesState>

    /** The daily job's status (GET /v1/job). Read-only. */
    suspend fun getJob(): Loaded<JobStatus>
}
