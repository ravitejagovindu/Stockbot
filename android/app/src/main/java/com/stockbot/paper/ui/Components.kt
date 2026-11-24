package com.stockbot.paper.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.stockbot.paper.data.Envelope
import com.stockbot.paper.data.Freshness
import com.stockbot.paper.format.RupeeFormat
import com.stockbot.paper.theme.StockBotTheme

/** A card. The only container the screens use. */
@Composable
fun PaperCard(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val t = StockBotTheme.tokens
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(t.cardCorner))
            .background(t.card)
            .padding(t.cardPadding),
    ) { content() }
}

/** A thin horizontal bar, filled to [fraction] (0 to 1), with an optional tick at [tick]. */
@Composable
fun PaperBar(fraction: Float, fill: Color, modifier: Modifier = Modifier, tick: Float? = null) {
    val t = StockBotTheme.tokens
    val shape = RoundedCornerShape(t.barHeight)
    Box(
        modifier
            .fillMaxWidth()
            .height(t.barHeight)
            .clip(shape)
            .background(t.hairline),
    ) {
        Box(
            Modifier
                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                .height(t.barHeight)
                .clip(shape)
                .background(fill),
        )
        if (tick != null) {
            val before = tick.coerceIn(0.01f, 0.99f)
            Row(Modifier.fillMaxSize()) {
                Box(Modifier.weight(before).height(t.barHeight))
                Box(Modifier.width(2.dp).height(t.barHeight).background(t.text.copy(alpha = 0.7f)))
                Box(Modifier.weight(1f - before).height(t.barHeight))
            }
        }
    }
}

/** A label above a value, used in rows of figures. */
@Composable
fun Stat(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = Color.Unspecified) {
    val type = StockBotTheme.type
    Column(modifier) {
        Text(label, style = type.label)
        Text(value, style = type.number.let { if (valueColor == Color.Unspecified) it else it.copy(color = valueColor) })
    }
}

/** The one-line note on a card whose figures may be off because of a corporate action. */
@Composable
fun CorporateActionNote() {
    Text("Corporate action: figures may be off", style = StockBotTheme.type.label.copy(color = StockBotTheme.tokens.warning), modifier = Modifier.padding(top = 6.dp))
}

@Composable
fun StaleLine(response: Envelope) {
    val line = Freshness.line(response) ?: return
    Text(line, style = StockBotTheme.type.label.copy(color = StockBotTheme.tokens.warning))
}

@Composable
fun LoadingBlock() {
    val t = StockBotTheme.tokens
    Column(Modifier.fillMaxWidth().padding(t.screenPadding), verticalArrangement = Arrangement.spacedBy(t.gap)) {
        Text("Loading", style = StockBotTheme.type.label)
        repeat(3) {
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(72.dp)
                    .clip(RoundedCornerShape(t.cardCorner))
                    .background(t.card),
            )
        }
    }
}

@Composable
fun ErrorBlock(message: String, onRetry: () -> Unit) {
    val t = StockBotTheme.tokens
    Column(
        Modifier.fillMaxSize().padding(t.screenPadding),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(message, style = StockBotTheme.type.body, textAlign = TextAlign.Center)
        TextButton(onClick = onRetry) {
            Text("Retry", style = StockBotTheme.type.bodyStrong.copy(color = t.accent))
        }
    }
}

/** An invitation shown when there is nothing to list yet. */
@Composable
fun EmptyBlock(title: String, body: String) {
    val t = StockBotTheme.tokens
    Column(Modifier.fillMaxWidth().padding(vertical = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(title, style = StockBotTheme.type.headline, textAlign = TextAlign.Center)
        Text(body, style = StockBotTheme.type.body.copy(color = t.muted), textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp))
    }
}

/**
 * Renders a screen from its state: loading, error with Retry, or a scrolling list that can be pulled down to refresh.
 * The list is built by [content], which receives the data and whether it is the empty case. When the data is the kept copy from the phone,
 * a calm line says so, with Retry.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun <T> StateHost(
    state: ScreenState<T>,
    onRetry: () -> Unit,
    refreshing: Boolean = false,
    onRefresh: (() -> Unit)? = null,
    content: LazyListScope.(data: T, isEmpty: Boolean) -> Unit,
) {
    when (state) {
        ScreenState.Loading -> LoadingBlock()
        is ScreenState.Error -> ErrorBlock(state.message, onRetry)
        is ScreenState.Empty -> Refreshable(refreshing, onRefresh) { ScreenList { offlineItem(state.offlineAt, onRetry); content(state.data, true) } }
        is ScreenState.Content -> Refreshable(refreshing, onRefresh) { ScreenList { offlineItem(state.offlineAt, onRetry); content(state.data, false) } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Refreshable(refreshing: Boolean, onRefresh: (() -> Unit)?, body: @Composable () -> Unit) {
    if (onRefresh == null) {
        body()
    } else {
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.fillMaxSize()) { body() }
    }
}

private fun LazyListScope.offlineItem(offlineAt: String?, onRetry: () -> Unit) {
    if (offlineAt != null) item { OfflineLine(offlineAt, onRetry) }
}

/** "Can't reach your laptop. Showing data from 24 Nov, 19:48." with Retry. */
@Composable
fun OfflineLine(generatedAt: String, onRetry: () -> Unit) {
    val t = StockBotTheme.tokens
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        Text(
            "Can't reach your laptop. Showing data from ${RupeeFormat.dateTime(generatedAt)}.",
            style = StockBotTheme.type.label.copy(color = t.warning),
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onRetry) { Text("Retry", style = StockBotTheme.type.bodyStrong.copy(color = t.accent)) }
    }
}

@Composable
private fun ScreenList(build: LazyListScope.() -> Unit) {
    val t = StockBotTheme.tokens
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = t.screenPadding, vertical = t.gap),
        verticalArrangement = Arrangement.spacedBy(t.gap),
        content = build,
    )
}
