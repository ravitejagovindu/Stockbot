package com.stockbot.paper.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.stockbot.paper.data.AccountSnapshot
import com.stockbot.paper.data.AccountSummary
import com.stockbot.paper.data.EquityPoint
import com.stockbot.paper.data.ReviewMarks
import com.stockbot.paper.format.RupeeFormat
import com.stockbot.paper.theme.StockBotTheme
import com.stockbot.paper.theme.ThemeTokens

/** The drawdown bar turns to the warning colour at this share of the review mark. */
const val DRAWDOWN_WARNING_FRACTION = 0.75f

/** Share of the drawdown review mark used, 0 to 1 (can exceed 1 past the mark). */
fun drawdownFraction(nowPct: Double, markPct: Double): Float = if (markPct <= 0.0) 0f else (nowPct / markPct).toFloat()

/** Bar colour: normal, warning near the mark, loss at or past it. */
fun drawdownColor(fraction: Float, t: ThemeTokens): Color = when {
    fraction >= 1f -> t.loss
    fraction >= DRAWDOWN_WARNING_FRACTION -> t.warning
    else -> t.accent
}

@Composable
fun AccountScreen(state: ScreenState<AccountSnapshot>, onRetry: () -> Unit) {
    StateHost(state, onRetry) { data, _ ->
        val s = data.summary
        item { StaleLine(s.asOf) }
        item { EquityCard(s) }
        item { CurveCard(data) }
        item { DrawdownCard(s, data.marks) }
        item { ClosedTradesCard(s, data.marks) }
        item {
            Text(
                "Verdict: ${data.marks.verdict.label}",
                style = StockBotTheme.type.label,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
            )
        }
    }
}

@Composable
private fun gainColor(value: Double): Color {
    val t = StockBotTheme.tokens
    return when {
        value > 0 -> t.gain
        value < 0 -> t.loss
        else -> t.text
    }
}

@Composable
private fun EquityCard(s: AccountSummary) {
    val type = StockBotTheme.type
    PaperCard {
        Text("Equity", style = type.label)
        Text(RupeeFormat.format(s.equity), style = type.numberLarge)
        Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("Account since ${RupeeFormat.date(s.startDate)}", RupeeFormat.percent(s.returnPct), valueColor = gainColor(s.returnPct))
            Stat("Nifty, same dates", RupeeFormat.percent(s.niftyReturnPct))
        }
    }
}

@Composable
private fun CurveCard(data: AccountSnapshot) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    val curve = data.curve
    PaperCard {
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("Account", style = type.label.copy(color = t.accent))
            Text("Nifty (dashed)", style = type.label)
        }
        EquityChart(
            curve, accent = t.accent, muted = t.muted, grid = t.hairline,
            modifier = Modifier.fillMaxWidth().height(160.dp).padding(top = 8.dp),
        )
        if (curve.size >= 2) {
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(RupeeFormat.date(curve.first().date), style = type.numberSmall)
                Text(RupeeFormat.date(curve.last().date), style = type.numberSmall)
            }
        }
        if (data.summary.closedTrades == 0 && curve.map { it.account }.distinct().size <= 1) {
            Text("The line moves after the first trade closes.", style = type.label, modifier = Modifier.padding(top = 8.dp))
        }
    }
}

/** Equity curve drawn by hand: solid account line, dashed muted Nifty line, three faint grid lines. */
@Composable
fun EquityChart(curve: List<EquityPoint>, accent: Color, muted: Color, grid: Color, modifier: Modifier = Modifier) {
    Canvas(modifier.semantics { contentDescription = "Equity curve of the account against Nifty" }) {
        if (curve.size < 2) return@Canvas
        val all = curve.flatMap { listOf(it.account, it.nifty) }
        val lo = all.min()
        val hi = all.max()
        val pad = ((hi - lo).takeIf { it > 0 } ?: (hi * 0.01)).times(0.08)
        val yMin = lo - pad
        val yMax = hi + pad
        fun x(i: Int) = size.width * i / (curve.size - 1)
        fun y(v: Double) = (size.height * (1 - (v - yMin) / (yMax - yMin))).toFloat()

        val hair = 1.dp.toPx()
        for (k in 0..2) {
            val gy = size.height * k / 2f
            drawLine(grid, Offset(0f, gy), Offset(size.width, gy), strokeWidth = hair)
        }
        fun path(pick: (EquityPoint) -> Double) = Path().apply {
            curve.forEachIndexed { i, p -> if (i == 0) moveTo(x(i), y(pick(p))) else lineTo(x(i), y(pick(p))) }
        }
        drawPath(
            path { it.nifty }, muted,
            style = Stroke(width = 1.5.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(10.dp.toPx(), 6.dp.toPx()))),
        )
        drawPath(path { it.account }, accent, style = Stroke(width = 2.dp.toPx()))
    }
}

@Composable
private fun DrawdownCard(s: AccountSummary, marks: ReviewMarks) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    val fraction = drawdownFraction(s.drawdownNowPct, marks.drawdownReviewPct)
    PaperCard {
        Text("Drawdown", style = type.label)
        Row(Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 10.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("Now", RupeeFormat.percent(s.drawdownNowPct, signed = false), valueColor = drawdownColor(fraction, t))
            Stat("Worst so far", RupeeFormat.percent(s.drawdownWorstPct, signed = false))
            Stat("Review at", RupeeFormat.percent(marks.drawdownReviewPct, signed = false))
        }
        PaperBar(fraction = fraction, fill = drawdownColor(fraction, t), tick = drawdownFraction(s.drawdownWorstPct, marks.drawdownReviewPct))
    }
}

@Composable
private fun ClosedTradesCard(s: AccountSummary, marks: ReviewMarks) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    PaperCard {
        Text("Closed trades", style = type.label)
        Text("${s.closedTrades} of ${marks.closedTradesTarget}", style = type.numberStrong, modifier = Modifier.padding(top = 2.dp, bottom = 10.dp))
        PaperBar(fraction = s.closedTrades.toFloat() / marks.closedTradesTarget, fill = t.accent)
    }
}
