package com.stockbot.paper.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * The single source of styling. Every colour, corner, spacing and font choice lives here;
 * screens read them from [StockBotTheme.tokens] and never hard-code a value.
 */
data class ThemeTokens(
    val isDark: Boolean,
    val background: Color,
    val card: Color,
    val text: Color,
    val muted: Color,
    val hairline: Color,
    val accent: Color,
    val gain: Color,
    val loss: Color,
    /** Drawdown bar when the account nears its review mark. */
    val warning: Color,
    val cardCorner: Dp,
    /** Padding inside a card. */
    val cardPadding: Dp,
    /** Gap between cards and between rows. */
    val gap: Dp,
    /** Horizontal screen margin. */
    val screenPadding: Dp,
    /** Font for every number; monospaced in the dark theme. */
    val numberFont: FontFamily,
    val barHeight: Dp,
)

object Palette {
    val Light = ThemeTokens(
        isDark = false,
        background = Color(0xFFF6F4EF),
        card = Color(0xFFFFFFFF),
        text = Color(0xFF2B2A27),
        muted = Color(0xFF7C776D),
        hairline = Color(0xFFE6E1D6),
        accent = Color(0xFF2F6F5E),
        gain = Color(0xFF2F6F5E),
        loss = Color(0xFFB5493A),
        warning = Color(0xFFB7791F),
        cardCorner = 16.dp,
        cardPadding = 16.dp,
        gap = 12.dp,
        screenPadding = 16.dp,
        numberFont = FontFamily.Default,
        barHeight = 8.dp,
    )

    val Dark = ThemeTokens(
        isDark = true,
        background = Color(0xFF0E1116),
        card = Color(0xFF161B22),
        text = Color(0xFFE6EDF3),
        muted = Color(0xFF7D8590),
        hairline = Color(0xFF262C36),
        accent = Color(0xFF3FB950),
        gain = Color(0xFF3FB950),
        loss = Color(0xFFF85149),
        warning = Color(0xFFD29922),
        cardCorner = 6.dp,
        cardPadding = 12.dp,
        gap = 8.dp,
        screenPadding = 12.dp,
        numberFont = FontFamily.Monospace,
        barHeight = 6.dp,
    )
}

/** Text styles, built from the tokens. */
class StockBotTypography(private val t: ThemeTokens) {
    val title = TextStyle(color = t.text, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
    val body = TextStyle(color = t.text, fontSize = 15.sp)
    val bodyStrong = TextStyle(color = t.text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
    val label = TextStyle(color = t.muted, fontSize = 12.sp)
    val tag = TextStyle(color = t.muted, fontSize = 10.sp, fontWeight = FontWeight.Medium, letterSpacing = 1.2.sp)
    val headline = TextStyle(color = t.text, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)

    /** Numbers: the theme's number font, with fixed-width digits. */
    val number = TextStyle(color = t.text, fontSize = 15.sp, fontFamily = t.numberFont, fontFeatureSettings = "tnum")
    val numberStrong = number.copy(fontWeight = FontWeight.SemiBold)
    val numberSmall = number.copy(fontSize = 13.sp, color = t.muted)
    val numberLarge = TextStyle(
        color = t.text, fontSize = 34.sp, fontWeight = FontWeight.SemiBold, fontFamily = t.numberFont, fontFeatureSettings = "tnum",
    )
}

private val LocalTokens = staticCompositionLocalOf { Palette.Light }
private val LocalTypography = staticCompositionLocalOf { StockBotTypography(Palette.Light) }

object StockBotTheme {
    val tokens: ThemeTokens @Composable get() = LocalTokens.current
    val type: StockBotTypography @Composable get() = LocalTypography.current
}

/** Resolves the saved mode to light or dark. */
@Composable
fun ThemeMode.resolveDark(): Boolean = when (this) {
    ThemeMode.LIGHT -> false
    ThemeMode.DARK -> true
    ThemeMode.SYSTEM -> isSystemInDarkTheme()
}

@Composable
fun StockBotTheme(mode: ThemeMode, content: @Composable () -> Unit) {
    val tokens = if (mode.resolveDark()) Palette.Dark else Palette.Light
    val colors = if (tokens.isDark) {
        darkColorScheme(
            primary = tokens.accent, background = tokens.background, surface = tokens.card,
            onBackground = tokens.text, onSurface = tokens.text, outline = tokens.hairline,
        )
    } else {
        lightColorScheme(
            primary = tokens.accent, background = tokens.background, surface = tokens.card,
            onBackground = tokens.text, onSurface = tokens.text, outline = tokens.hairline,
        )
    }
    CompositionLocalProvider(LocalTokens provides tokens, LocalTypography provides StockBotTypography(tokens)) {
        MaterialTheme(colorScheme = colors, content = content)
    }
}
