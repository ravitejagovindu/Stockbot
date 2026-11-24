package com.stockbot.paper

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import com.stockbot.paper.theme.ThemeMode
import com.stockbot.paper.theme.ThemeModeStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.io.File

class ThemeModeStoreTest {
    private lateinit var file: File
    private val scopes = mutableListOf<CoroutineScope>()

    @Before fun setUp() {
        file = File.createTempFile("settings", ".preferences_pb").also { it.delete() }
    }

    @After fun tearDown() {
        scopes.forEach { it.cancel() }
        file.delete()
    }

    private fun dataStore() = PreferenceDataStoreFactory.create(
        scope = CoroutineScope(Dispatchers.IO + Job()).also { scopes.add(it) },
        produceFile = { file },
    )

    @Test fun defaultsToSystem() = runBlocking {
        assertEquals(ThemeMode.SYSTEM, ThemeModeStore(dataStore()).mode.first())
    }

    @Test fun savesEachMode() = runBlocking {
        val store = ThemeModeStore(dataStore())
        for (m in ThemeMode.entries) {
            store.set(m)
            assertEquals(m, store.mode.first())
        }
    }

    @Test fun choiceSurvivesARestart() = runBlocking {
        ThemeModeStore(dataStore()).set(ThemeMode.DARK)
        // A restart opens the same file in a new process. DataStore refuses two live instances on one path in a single
        // process, so a byte-for-byte copy of the saved file stands in for "the file that is left after the app closes".
        val afterRestart = File.createTempFile("settings-restart", ".preferences_pb")
        try {
            file.copyTo(afterRestart, overwrite = true)
            val reopened = PreferenceDataStoreFactory.create(
                scope = CoroutineScope(Dispatchers.IO + Job()).also { scopes.add(it) },
                produceFile = { afterRestart },
            )
            assertEquals(ThemeMode.DARK, ThemeModeStore(reopened).mode.first())
        } finally {
            afterRestart.delete()
        }
    }

    @Test fun unknownStoredValueFallsBackToSystem() = runBlocking {
        val ds = dataStore()
        ds.edit { it[stringPreferencesKey("theme_mode")] = "PURPLE" }
        assertEquals(ThemeMode.SYSTEM, ThemeModeStore(ds).mode.first())
    }

    @Test fun parseHandlesNullAndNames() {
        assertEquals(ThemeMode.SYSTEM, ThemeMode.parse(null))
        assertEquals(ThemeMode.LIGHT, ThemeMode.parse("LIGHT"))
        assertEquals(ThemeMode.DARK, ThemeMode.parse("DARK"))
        assertEquals(ThemeMode.SYSTEM, ThemeMode.parse("dark"))
    }
}
