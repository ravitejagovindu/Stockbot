package com.stockbot.paper.ui

import com.stockbot.paper.data.AccountSnapshot
import com.stockbot.paper.data.JobStatus
import com.stockbot.paper.data.Loaded
import com.stockbot.paper.data.PaperRepository
import com.stockbot.paper.data.PositionsState
import com.stockbot.paper.data.TodayState
import com.stockbot.paper.data.TradesState
import kotlinx.coroutines.CancellationException

/** What a screen shows. The UI renders exactly one of these. */
sealed interface ScreenState<out T> {
    data object Loading : ScreenState<Nothing>

    /** The data loaded and there is nothing to list yet; the screen shows an invitation. */
    data class Empty<T>(val data: T, val offlineAt: String? = null) : ScreenState<T>

    data class Error(val message: String) : ScreenState<Nothing>

    data class Content<T>(val data: T, val offlineAt: String? = null) : ScreenState<T>
}

/** Turns repository calls into [ScreenState]. The only place that decides what counts as empty or as an error. */
class ScreenLoader(private val repo: PaperRepository) {
    /** Today is empty on a non-signal day with nothing pending: it then shows "No signal today". */
    suspend fun today(): ScreenState<TodayState> =
        load({ it.tickets.isEmpty() && it.pendingFills.isEmpty() }) { repo.getToday() }

    /** The account always has figures to show, so it is never empty. */
    suspend fun account(): ScreenState<AccountSnapshot> = load({ false }) { repo.getAccount() }

    suspend fun positions(): ScreenState<PositionsState> = load({ it.positions.isEmpty() }) { repo.getPositions() }

    suspend fun trades(): ScreenState<TradesState> = load({ it.trades.isEmpty() }) { repo.getTrades() }

    /** The job status always has something to show, so it is never empty. */
    suspend fun job(): ScreenState<JobStatus> = load({ false }) { repo.getJob() }

    private suspend fun <T> load(isEmpty: (T) -> Boolean, block: suspend () -> Loaded<T>): ScreenState<T> =
        try {
            val loaded = block()
            if (isEmpty(loaded.data)) ScreenState.Empty(loaded.data, loaded.offlineGeneratedAt) else ScreenState.Content(loaded.data, loaded.offlineGeneratedAt)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ScreenState.Error(ERROR_MESSAGE)
        }

    companion object {
        const val ERROR_MESSAGE = "Could not load this screen."
    }
}
