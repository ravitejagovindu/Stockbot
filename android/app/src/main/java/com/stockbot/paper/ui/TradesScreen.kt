package com.stockbot.paper.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.stockbot.paper.data.ClosedTrade
import com.stockbot.paper.data.TradeStats
import com.stockbot.paper.data.TradesState
import com.stockbot.paper.format.RupeeFormat
import com.stockbot.paper.theme.StockBotTheme
import java.util.Locale

@Composable
fun TradesScreen(state: ScreenState<TradesState>, onRetry: () -> Unit, refreshing: Boolean = false, onRefresh: (() -> Unit)? = null) {
    StateHost(state, onRetry, refreshing, onRefresh) { data, isEmpty ->
        item { StaleLine(data) }
        if (isEmpty) {
            item { EmptyBlock("No closed trades yet", "Finished trades are listed here, newest first.") }
        } else {
            items(data.trades, key = { "${it.symbol}-${it.exitDate}" }) { TradeCard(it) }
            item { StatsFooter(data.stats) }
        }
    }
}

@Composable
private fun TradeCard(tr: ClosedTrade) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    val color = if (tr.netPnlPaise >= 0) t.gain else t.loss
    PaperCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
            Column {
                Text(tr.symbol, style = type.title)
                Text("${RupeeFormat.date(tr.entryDate)} to ${RupeeFormat.date(tr.exitDate)}", style = type.label)
                Text(tr.exitReason.label, style = type.label)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(RupeeFormat.format(tr.netPnlPaise, signed = true), style = type.numberStrong.copy(color = color))
                Text(RupeeFormat.r(tr.netR), style = type.numberSmall.copy(color = color))
                Text("After costs", style = type.label)
            }
        }
        if (tr.corporateActionFlag) CorporateActionNote()
    }
}

@Composable
private fun StatsFooter(stats: TradeStats) {
    PaperCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("Win rate", stats.winRatePct?.let { "${RupeeFormat.wholePercent(it)} (${stats.wins} of ${stats.tradeCount - stats.excludedFromStats})" } ?: "n/a")
            Stat("Profit factor", stats.profitFactor?.let { String.format(Locale.US, "%.2f", it) } ?: "n/a")
        }
        if (stats.excludedFromStats > 0) {
            val n = stats.excludedFromStats
            Text(if (n == 1) "1 trade excluded: corporate action" else "$n trades excluded: corporate action", style = StockBotTheme.type.label, modifier = Modifier.padding(top = 8.dp))
        }
    }
}
