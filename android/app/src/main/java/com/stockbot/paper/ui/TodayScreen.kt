package com.stockbot.paper.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.stockbot.paper.data.BlockReason
import com.stockbot.paper.data.PendingFill
import com.stockbot.paper.data.Side
import com.stockbot.paper.data.Ticket
import com.stockbot.paper.data.TodayState
import com.stockbot.paper.format.RupeeFormat
import com.stockbot.paper.theme.StockBotTheme

@Composable
fun TodayScreen(state: ScreenState<TodayState>, onRetry: () -> Unit, refreshing: Boolean = false, onRefresh: (() -> Unit)? = null) {
    StateHost(state, onRetry, refreshing, onRefresh) { data, _ ->
        item { StaleLine(data) }
        if (data.isSignalDay && data.tickets.isNotEmpty()) {
            item { SignalHeader(data) }
            items(data.tickets, key = { it.symbol }) { TicketCard(it) }
            val sectorBlocked = data.blocked.count { it.reason == BlockReason.SECTOR_CAP }
            if (sectorBlocked > 0) item { BlockedLine(sectorBlocked) }
        } else {
            item { NoSignalHeader(data) }
            items(data.pendingFills, key = { it.symbol }) { PendingFillCard(it) }
        }
    }
}

@Composable
private fun SignalHeader(data: TodayState) {
    val type = StockBotTheme.type
    val n = data.tickets.size
    val risk = RupeeFormat.wholeOrOneDecimal(data.riskPerTradePct)
    Column(Modifier.padding(vertical = 4.dp)) {
        Text(if (n == 1) "1 suggestion" else "$n suggestions", style = type.headline)
        Text("Buy at tomorrow's open. Risk $risk% each.", style = type.body.copy(color = StockBotTheme.tokens.muted))
    }
}

@Composable
private fun NoSignalHeader(data: TodayState) {
    val type = StockBotTheme.type
    Column(Modifier.padding(vertical = 4.dp)) {
        Text("No signal today", style = type.headline)
        Text("Next signal: ${data.nextSignalRule}", style = type.body.copy(color = StockBotTheme.tokens.muted))
    }
}

@Composable
private fun TicketCard(t: Ticket) {
    val type = StockBotTheme.type
    PaperCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column {
                Text(t.symbol, style = type.title)
                t.sector?.let { Text(it, style = type.label) }
            }
            Stat("Risk", RupeeFormat.format(t.riskPaise))
        }
        Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("Shares", t.shares.toString())
            Stat("Entry ref", RupeeFormat.format(t.entryReferencePaise))
            Stat("Stop", RupeeFormat.format(t.stopPaise))
        }
    }
}

@Composable
private fun BlockedLine(k: Int) {
    val text = if (k == 1) "1 more was blocked by the sector cap" else "$k more were blocked by the sector cap"
    Text(text, style = StockBotTheme.type.label, modifier = Modifier.padding(horizontal = 4.dp))
}

@Composable
private fun PendingFillCard(p: PendingFill) {
    val type = StockBotTheme.type
    val verb = when (p.side) {
        Side.BUY -> "Buy"
        Side.SELL -> "Sell"
        Side.OTHER -> "Order for"
    }
    PaperCard {
        Text("Pending", style = type.label)
        Text("$verb ${p.shares} ${p.symbol} at tomorrow's open", style = type.bodyStrong)
        Text(p.note, style = type.label)
    }
}
