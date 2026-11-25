package com.stockbot.paper.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.stockbot.paper.data.JobDay
import com.stockbot.paper.data.JobState
import com.stockbot.paper.data.JobStatus
import com.stockbot.paper.format.JobFormat
import com.stockbot.paper.format.RupeeFormat
import com.stockbot.paper.theme.StockBotTheme
import com.stockbot.paper.theme.ThemeTokens
import kotlin.math.cos
import kotlin.math.sin

/** How many chips the strip shows: the last ten days. */
const val HISTORY_SLOTS = 10

/** The colour of a state. It is never the only signal: the word and the icon always come with it. */
fun stateColor(state: JobState, t: ThemeTokens): Color = when (state) {
    JobState.DONE -> t.gain
    JobState.RUNNING -> t.accent
    JobState.RETRYING -> t.warning
    JobState.ALERT -> t.loss
    JobState.NO_FILE, JobState.WAITING, JobState.WEEKEND -> t.muted
}

/** The Job screen: one question, "did tonight's job run?". Read-only: there is no button that changes anything. */
@Composable
fun JobScreen(state: ScreenState<JobStatus>, onRetry: () -> Unit, refreshing: Boolean = false, onRefresh: (() -> Unit)? = null) {
    StateHost(state, onRetry, refreshing, onRefresh) { data, _ ->
        item { StatusCard(data) }
        item { HistoryCard(data.history) }
        item { AttemptsCard(data) }
    }
}

@Composable
private fun StatusCard(s: JobStatus) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    val color = stateColor(s.today.state, t)
    PaperCard {
        Row(
            Modifier
                .clip(RoundedCornerShape(t.cardCorner))
                .background(color.copy(alpha = 0.14f))
                .border(1.dp, color.copy(alpha = 0.55f), RoundedCornerShape(t.cardCorner))
                .padding(horizontal = 14.dp, vertical = 10.dp)
                .semantics { contentDescription = JobFormat.description(s.today.state) },
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            StateIcon(s.today.state, color, 28.dp)
            Text(JobFormat.word(s.today.state), style = type.headline.copy(color = color))
        }
        Text(s.today.message, style = type.body, modifier = Modifier.padding(top = 10.dp))
        Row(Modifier.fillMaxWidth().padding(top = 14.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("Service", JobFormat.serviceLine(s.service))
            Stat("Next attempt", JobFormat.nextAttempt(s.nextAttemptAt, s.service.running))
        }
        Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Stat("Data as of", s.data.latestSealedDate?.let { RupeeFormat.date(it) } ?: "Not known")
            Stat("Expected", RupeeFormat.date(s.data.expectedAsOf))
            Stat("Data", JobFormat.dataStatus(s.data))
        }
    }
}

@Composable
private fun HistoryCard(days: List<JobDay>) {
    val type = StockBotTheme.type
    PaperCard {
        Text("Last 10 days", style = type.label)
        Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            repeat((HISTORY_SLOTS - days.size).coerceAtLeast(0)) { Spacer(Modifier.weight(1f)) }
            days.takeLast(HISTORY_SLOTS).forEach { d -> HistoryChip(d, Modifier.weight(1f)) }
        }
    }
}

@Composable
private fun HistoryChip(d: JobDay, modifier: Modifier) {
    val t = StockBotTheme.tokens
    val type = StockBotTheme.type
    val color = stateColor(d.state, t)
    Column(
        modifier.semantics { contentDescription = "${JobFormat.weekday(d.date)} ${JobFormat.dayOfMonth(d.date)}: ${JobFormat.description(d.state)}" },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(JobFormat.weekday(d.date).take(3), style = type.label.copy(fontSize = 10.sp))
        Box(
            Modifier
                .padding(vertical = 3.dp)
                .size(30.dp)
                .clip(RoundedCornerShape(if (t.isDark) 4.dp else 8.dp))
                .background(color.copy(alpha = 0.14f))
                .border(1.dp, color.copy(alpha = 0.55f), RoundedCornerShape(if (t.isDark) 4.dp else 8.dp)),
            contentAlignment = Alignment.Center,
        ) { StateIcon(d.state, color, 16.dp) }
        Text(JobFormat.dayOfMonth(d.date), style = type.numberSmall)
    }
}

@Composable
private fun AttemptsCard(s: JobStatus) {
    val type = StockBotTheme.type
    val rows = JobFormat.todayAttempts(s)
    PaperCard {
        Text("Today's attempts", style = type.label)
        if (rows.isEmpty()) {
            Text("No attempts yet today.", style = type.body.copy(color = StockBotTheme.tokens.muted), modifier = Modifier.padding(top = 6.dp))
        } else {
            rows.forEach { a ->
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text(JobFormat.time(a.at), style = type.numberStrong, modifier = Modifier.width(64.dp))
                    Text("exit ${a.exitCode}", style = type.numberSmall, modifier = Modifier.weight(1f), textAlign = TextAlign.Start)
                    Text(a.decision.label, style = type.bodyStrong)
                }
            }
        }
    }
}

/** A small icon per state, drawn by hand (no icon library): check, play, circular arrow, ring with a slash, triangle, clock, pause. */
@Composable
fun StateIcon(state: JobState, color: Color, size: Dp) {
    Canvas(Modifier.size(size)) { drawState(state, color) }
}

private fun DrawScope.drawState(state: JobState, color: Color) {
    val w = size.width
    val h = size.height
    val sw = (w * 0.11f).coerceAtLeast(1.6f)
    val line = Stroke(width = sw, cap = StrokeCap.Round, join = StrokeJoin.Round)
    val c = Offset(w / 2, h / 2)
    val r = w * 0.40f
    when (state) {
        JobState.DONE -> drawPath(
            Path().apply { moveTo(w * 0.20f, h * 0.54f); lineTo(w * 0.42f, h * 0.74f); lineTo(w * 0.80f, h * 0.28f) },
            color, style = line,
        )
        JobState.RUNNING -> drawPath(
            Path().apply { moveTo(w * 0.30f, h * 0.20f); lineTo(w * 0.30f, h * 0.80f); lineTo(w * 0.80f, h * 0.50f); close() },
            color, style = Fill,
        )
        JobState.RETRYING -> {
            val start = 40f
            val sweep = 280f
            drawArc(color, start, sweep, false, topLeft = Offset(c.x - r, c.y - r), size = Size(2 * r, 2 * r), style = line)
            val end = Math.toRadians((start + sweep).toDouble())
            val tip = Offset(c.x + r * cos(end).toFloat(), c.y + r * sin(end).toFloat())
            val tx = (-sin(end)).toFloat()
            val ty = cos(end).toFloat()
            val len = w * 0.22f
            drawLine(color, tip, Offset(tip.x - len * tx + len * 0.6f * (-ty), tip.y - len * ty + len * 0.6f * tx), strokeWidth = sw, cap = StrokeCap.Round)
            drawLine(color, tip, Offset(tip.x - len * tx - len * 0.6f * (-ty), tip.y - len * ty - len * 0.6f * tx), strokeWidth = sw, cap = StrokeCap.Round)
        }
        JobState.NO_FILE -> {
            drawCircle(color, r, c, style = line)
            drawLine(color, Offset(c.x - r * 0.7f, c.y + r * 0.7f), Offset(c.x + r * 0.7f, c.y - r * 0.7f), strokeWidth = sw, cap = StrokeCap.Round)
        }
        JobState.ALERT -> {
            drawPath(Path().apply { moveTo(w * 0.5f, h * 0.12f); lineTo(w * 0.92f, h * 0.84f); lineTo(w * 0.08f, h * 0.84f); close() }, color, style = line)
            drawLine(color, Offset(w * 0.5f, h * 0.38f), Offset(w * 0.5f, h * 0.60f), strokeWidth = sw, cap = StrokeCap.Round)
            drawCircle(color, sw * 0.7f, Offset(w * 0.5f, h * 0.73f))
        }
        JobState.WAITING -> {
            drawCircle(color, r, c, style = line)
            drawLine(color, c, Offset(c.x, c.y - r * 0.6f), strokeWidth = sw, cap = StrokeCap.Round)
            drawLine(color, c, Offset(c.x + r * 0.45f, c.y + r * 0.2f), strokeWidth = sw, cap = StrokeCap.Round)
        }
        JobState.WEEKEND -> {
            drawCircle(color, r, c, style = line)
            drawLine(color, Offset(c.x - r * 0.28f, c.y - r * 0.4f), Offset(c.x - r * 0.28f, c.y + r * 0.4f), strokeWidth = sw, cap = StrokeCap.Round)
            drawLine(color, Offset(c.x + r * 0.28f, c.y - r * 0.4f), Offset(c.x + r * 0.28f, c.y + r * 0.4f), strokeWidth = sw, cap = StrokeCap.Round)
        }
    }
}
