package com.stockbot.paper.theme

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** The in-app override for light or dark. SYSTEM follows the phone's setting. */
enum class ThemeMode(val label: String) {
    SYSTEM("System"),
    LIGHT("Light"),
    DARK("Dark"),
    ;

    companion object {
        /** An unknown or missing stored value falls back to SYSTEM. */
        fun parse(stored: String?): ThemeMode = entries.firstOrNull { it.name == stored } ?: SYSTEM
    }
}

/** Saves the chosen [ThemeMode] in DataStore. */
class ThemeModeStore(private val dataStore: DataStore<Preferences>) {
    val mode: Flow<ThemeMode> = dataStore.data.map { ThemeMode.parse(it[KEY]) }

    suspend fun set(mode: ThemeMode) {
        dataStore.edit { it[KEY] = mode.name }
    }

    private companion object {
        val KEY = stringPreferencesKey("theme_mode")
    }
}
