package com.stockbot.paper

import com.stockbot.paper.data.Contract
import com.stockbot.paper.data.JobDecision
import com.stockbot.paper.data.JobScenario
import com.stockbot.paper.data.JobState
import com.stockbot.paper.data.JobStatus
import com.stockbot.paper.data.MockPaperRepository
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.format.JobFormat
import com.stockbot.paper.theme.Palette
import com.stockbot.paper.ui.ScreenLoader
import com.stockbot.paper.ui.ScreenState
import com.stockbot.paper.ui.stateColor
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/** The Job screen: the example files of GET /v1/job, the mock scenarios, the mapping of states to words and colours, and the small formatting functions. */
class JobStatusTest {
    private fun job(scenario: JobScenario): JobStatus = Contract.job(TestExamples.source.read(scenario.file))

    // ------------------------------------------------------------------------------------------------------------------ the example files
    @Test fun everyJobScenarioFileParsesAndShowsItsState() {
        val expected = mapOf(
            JobScenario.DONE to JobState.DONE, JobScenario.RUNNING to JobState.RUNNING, JobScenario.RETRYING to JobState.RETRYING,
            JobScenario.NO_FILE to JobState.NO_FILE, JobScenario.ALERT to JobState.ALERT, JobScenario.SERVICE_OFF to JobState.WAITING,
        )
        for (s in JobScenario.entries) assertEquals("$s", expected[s], job(s).today.state)
    }

    @Test fun theExamplesAreConsistentWithTheirOwnStateRules() {
        for (s in JobScenario.entries) {
            val j = job(s)
            assertEquals("${s} apiVersion", "1", j.apiVersion)
            assertTrue("$s history is at most 10 days, oldest first, today last", j.history.size <= 10 && j.history.zipWithNext().all { (a, b) -> a.date < b.date })
            assertEquals("$s today is the last history day", j.today.date, j.history.last().date)
            assertEquals("$s today state matches the history", j.today.state, j.history.last().state)
            assertTrue("$s at most 20 attempts, newest first", j.attempts.size <= 20 && j.attempts.zipWithNext().all { (a, b) -> a.at >= b.at })
            assertEquals("$s today attempts counted from the list", j.today.attempts, JobFormat.todayAttempts(j).count { it.decision != JobDecision.CATCH_UP })
            when (j.today.state) {
                JobState.DONE -> { assertEquals(0, j.today.lastExitCode); assertNull(j.nextAttemptAt) }
                JobState.RETRYING -> { assertEquals(3, j.today.lastExitCode); assertTrue(j.nextAttemptAt != null) }
                JobState.RUNNING -> assertNull(j.nextAttemptAt)
                JobState.NO_FILE -> { assertEquals(3, j.today.lastExitCode); assertTrue(j.today.message.contains("holiday")) }
                JobState.ALERT -> assertTrue(j.today.lastExitCode != 0)
                JobState.WAITING -> assertEquals(0, j.today.attempts)
                JobState.WEEKEND -> assertTrue(j.today.date.dayOfWeek.value >= 6)
            }
            assertFalse("$s calm copy", j.today.message.contains("!") || j.today.message.lowercase().contains("please"))
            if (!j.service.running) assertNull("$s service off has no next attempt", j.nextAttemptAt)
        }
    }

    @Test fun theRealDayIsInTheDoneExample() {
        val j = job(JobScenario.DONE)
        assertEquals(LocalDate.of(2026, 11, 25), j.today.date)
        assertEquals(1, j.today.attempts)
        assertEquals("19:47", JobFormat.time(j.today.lastAttemptAt))
        assertEquals(JobState.NO_FILE, j.history.first { it.date == LocalDate.of(2026, 11, 24) }.state)
        assertEquals(12, j.history.first { it.date == LocalDate.of(2026, 11, 24) }.attempts)
        assertEquals(9100, j.service.pid)
    }

    // ------------------------------------------------------------------------------------------------------------------ the mock path
    @Test fun theMockRepositoryServesEveryJobScenarioAndTheLoaderGivesContent() = runBlocking {
        val repo = MockPaperRepository(TestExamples.source, Scenario.EMPTY, latencyMs = 0)
        val loader = ScreenLoader(repo)
        for (s in JobScenario.entries) {
            repo.selectJob(s)
            val st = loader.job()
            assertTrue("$s", st is ScreenState.Content)
            assertEquals(s.file, s.file)
        }
        repo.select(Scenario.ERROR)
        assertEquals(ScreenState.Error(ScreenLoader.ERROR_MESSAGE), loader.job())
    }

    // ------------------------------------------------------------------------------------------------------------------ unknown values never crash
    @Test fun anUnknownStateOrDecisionBecomesAlert() {
        val base = TestExamples.source.read("job.json")
        val tampered = base.replace("\"state\": \"DONE\"", "\"state\": \"SOMETHING_NEW\"").replace("\"decision\": \"done\"", "\"decision\": \"surprise\"")
        val j = Contract.job(tampered)
        assertEquals(JobState.ALERT, j.today.state)
        assertTrue(j.attempts.any { it.decision == JobDecision.ALERT })
        assertEquals(JobDecision.CATCH_UP, job(JobScenario.DONE).attempts.first { it.exitCode == 0 && it.at.contains("08:30") }.decision)
    }

    @Test fun unknownKeysAndNullsAreFine() {
        val j = Contract.job(TestExamples.source.read("job_service_off.json").replace("\"running\": false,", "\"running\": false, \"extra\": 1,"))
        assertFalse(j.service.running)
        assertNull(j.nextAttemptAt)
    }

    // ------------------------------------------------------------------------------------------------------------------ words, colours, texts
    @Test fun everyStateHasADifferentWordAndTheWordIsNeverColourAlone() {
        val words = JobState.entries.map { JobFormat.word(it) }
        assertEquals(JobState.entries.size, words.toSet().size)
        assertEquals(listOf("Done", "Running", "Retrying", "No file", "Alert", "Waiting", "Weekend"), words)
        JobState.entries.forEach { assertTrue(JobFormat.description(it).startsWith(JobFormat.word(it))) }
    }

    @Test fun colourMappingUsesTheThemeAndSeparatesTheCriticalStates() {
        for (t in listOf(Palette.Light, Palette.Dark)) {
            assertEquals(t.gain, stateColor(JobState.DONE, t))
            assertEquals(t.accent, stateColor(JobState.RUNNING, t))
            assertEquals(t.warning, stateColor(JobState.RETRYING, t))
            assertEquals(t.loss, stateColor(JobState.ALERT, t))
            assertEquals(t.muted, stateColor(JobState.NO_FILE, t))
            assertEquals(t.muted, stateColor(JobState.WAITING, t))
            assertNotEquals(stateColor(JobState.DONE, t), stateColor(JobState.ALERT, t))
            assertNotEquals(stateColor(JobState.RETRYING, t), stateColor(JobState.ALERT, t))
        }
    }

    @Test fun timeAndTextFormatting() {
        assertEquals("19:47", JobFormat.time("2026-11-25T19:47:49+05:30"))
        assertEquals("—", JobFormat.time(null))
        assertEquals("—", JobFormat.time("not a time"))
        assertEquals("23 Nov, 17:43", JobFormat.dayTime("2026-11-23T17:43:25+05:30"))
        assertEquals("Wed", JobFormat.weekday(LocalDate.of(2026, 11, 25)))
        assertEquals("25", JobFormat.dayOfMonth(LocalDate.of(2026, 11, 25)))
        assertEquals("—", JobFormat.exitCode(null))
        assertEquals("3", JobFormat.exitCode(3))
    }

    @Test fun serviceAndNextAttemptLines() {
        assertEquals("On, since 23 Nov, 17:43", JobFormat.serviceLine(job(JobScenario.DONE).service))
        assertEquals("Off", JobFormat.serviceLine(job(JobScenario.SERVICE_OFF).service))
        assertEquals("20:50", JobFormat.nextAttempt(job(JobScenario.RETRYING).nextAttemptAt, true))
        assertEquals("None", JobFormat.nextAttempt(null, true))
        assertEquals("None (service off)", JobFormat.nextAttempt(null, false))
    }

    @Test fun dataStatusLine() {
        val d = job(JobScenario.DONE).data
        assertEquals("Up to date", JobFormat.dataStatus(d))
        assertEquals("1 day behind", JobFormat.dataStatus(d.copy(latestSealedDate = d.expectedAsOf.minusDays(1))))
        assertEquals("3 days behind", JobFormat.dataStatus(d.copy(latestSealedDate = d.expectedAsOf.minusDays(3))))
        assertEquals("Not known", JobFormat.dataStatus(d.copy(latestSealedDate = null)))
        val noFile = job(JobScenario.NO_FILE)
        assertEquals("1 day behind", JobFormat.dataStatus(noFile.data))
    }

    @Test fun todaysAttemptListIsOnlyTodaysAttemptsInTheSentOrder() {
        val j = job(JobScenario.RETRYING)
        val rows = JobFormat.todayAttempts(j)
        assertEquals(5, rows.size)                                   // four evening attempts and the 08:30 catch-up of the same day
        assertEquals(listOf("20:30", "20:10", "19:50", "19:30", "08:30"), rows.map { JobFormat.time(it.at) })
        assertTrue(rows.take(4).all { it.decision == JobDecision.RETRY } && rows.last().decision == JobDecision.CATCH_UP)
        assertEquals("20:30  exit 3  Retry", JobFormat.attemptLine(rows.first()))
        // yesterday's lines are not in today's list
        assertTrue(JobFormat.todayAttempts(job(JobScenario.DONE)).size == 2)
    }
}
