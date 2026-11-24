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
import com.stockbot.paper.data.Position
import com.stockbot.paper.data.PositionsState
import com.stockbot.paper.format.RupeeFormat
import com.stockbot.paper.theme.StockBotTheme

@Composable
fun PositionsScreen(state: ScreenState<PositionsState>, onRetry: () -> Unit) {
    StateHost(state, onRetry) { data, isEmpty ->
        item { StaleLine(data.asOf) }
        if (isEmpty) {
            item { EmptyBlock("Nothing open yet", "Positions appear here after a signal day fills.") }
        } else {
            items(data.positions, key = { it.symbol }) { PositionCard(it) }
        }
        item { CashFooter(data.cash) }
    }
}

@Composable
private fun PositionCard(p: Position) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    val pnlColor = if (p.unrealisedPnl >= 0) t.gain else t.loss
    PaperCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
            Column {
                Text(p.symbol, style = type.title)
                Text("${p.shares} shares since ${RupeeFormat.date(p.entryDate)}", style = type.label)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(RupeeFormat.format(p.unrealisedPnl, signed = true), style = type.numberStrong.copy(color = pnlColor))
                Text("Unrealised", style = type.label)
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("Entry", RupeeFormat.format(p.entryPrice))
            Stat("Stop", RupeeFormat.format(p.stop))
            Stat("Last close", RupeeFormat.format(p.lastClose))
        }
    }
}

@Composable
private fun CashFooter(cash: Double) {
    val type = StockBotTheme.type
    PaperCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("Cash", style = type.label)
            Text(RupeeFormat.format(cash), style = type.numberStrong)
        }
        Text("Idle cash earns nothing", style = type.label, modifier = Modifier.padding(top = 4.dp))
    }
}
