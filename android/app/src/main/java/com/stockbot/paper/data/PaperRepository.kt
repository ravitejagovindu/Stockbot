package com.stockbot.paper.data

/**
 * What the UI knows about the data. One call per screen; any call may throw, and the UI shows a calm error with Retry.
 * Stage 1 has only a mock implementation; later stages add one that reads the backend.
 */
interface PaperRepository {
    /** True while the data is made up. Drives the "SAMPLE DATA" tag. */
    val isSample: Boolean

    suspend fun getToday(): TodayState
    suspend fun getAccount(): AccountSnapshot
    suspend fun getPositions(): PositionsState
    suspend fun getTrades(): TradesState
}
