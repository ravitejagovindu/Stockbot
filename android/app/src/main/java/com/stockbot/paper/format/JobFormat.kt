package com.stockbot.paper.format

import com.stockbot.paper.data.Freshness
import com.stockbot.paper.data.JobAttempt
import com.stockbot.paper.data.JobData
import com.stockbot.paper.data.JobService
import com.stockbot.paper.data.JobState
import com.stockbot.paper.data.JobStatus
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/** The words and small texts of the Job screen, as pure functions (unit tested). Colour and icon are chosen in the screen; the word is always shown, so state is never colour alone. */
object JobFormat {
    fun word(state: JobState): String = when (state) {
        JobState.DONE -> "Done"
        JobState.RUNNING -> "Running"
        JobState.RETRYING -> "Retrying"
        JobState.NO_FILE -> "No file"
        JobState.ALERT -> "Alert"
        JobState.WAITING -> "Waiting"
        JobState.WEEKEND -> "Weekend"
    }

    /** A hint for people who use a screen reader or cannot see colour. */
    fun description(state: JobState): String = when (state) {
        JobState.DONE -> "Done: the job finished for the day"
        JobState.RUNNING -> "Running: the job is running now"
        JobState.RETRYING -> "Retrying: the data file is not out yet"
        JobState.NO_FILE -> "No file: no data was published, probably a holiday"
        JobState.ALERT -> "Alert: the job stopped and needs a look"
        JobState.WAITING -> "Waiting: the job has not started yet"
        JobState.WEEKEND -> "Weekend: no market session"
    }

    private val TIME = DateTimeFormatter.ofPattern("HH:mm", Locale.ENGLISH)
    private val DAY_TIME = DateTimeFormatter.ofPattern("d MMM, HH:mm", Locale.ENGLISH)
    private val WEEKDAY = DateTimeFormatter.ofPattern("EEE", Locale.ENGLISH)

    private fun parse(iso: String?): OffsetDateTime? = try { iso?.let { OffsetDateTime.parse(it) } } catch (e: Exception) { null }

    /** "19:47" from an ISO timestamp (its own offset is kept); a dash when there is none or it cannot be read. */
    fun time(iso: String?): String = parse(iso)?.format(TIME) ?: "—"

    /** "23 Nov, 17:43". */
    fun dayTime(iso: String?): String = parse(iso)?.format(DAY_TIME) ?: "—"

    /** "Wed" for a date, and the day of the month for the history chips. */
    fun weekday(d: LocalDate): String = d.format(WEEKDAY)
    fun dayOfMonth(d: LocalDate): String = d.dayOfMonth.toString()

    fun serviceLine(s: JobService): String =
        if (s.running) (s.startedAt?.let { "On, since ${dayTime(it)}" } ?: "On") else "Off"

    /** "20:50", or "None" when no attempt is due. */
    fun nextAttempt(iso: String?, serviceRunning: Boolean): String = when {
        iso != null -> time(iso)
        !serviceRunning -> "None (service off)"
        else -> "None"
    }

    /** "Up to date", "1 day behind", "3 days behind", or "Not known". */
    fun dataStatus(d: JobData): String {
        val sealed = d.latestSealedDate ?: return "Not known"
        return when (val n = Freshness.daysBehind(sealed, d.expectedAsOf)) {
            null -> "Up to date"
            1 -> "1 day behind"
            else -> "$n days behind"
        }
    }

    fun exitCode(code: Int?): String = code?.toString() ?: "—"

    /** The attempts logged on [day] (the status's own today), newest first as sent. */
    fun attemptsOn(day: LocalDate, all: List<JobAttempt>): List<JobAttempt> = all.filter { parse(it.at)?.toLocalDate() == day }

    /** "19:47  exit 0  Done". */
    fun attemptLine(a: JobAttempt): String = "${time(a.at)}  exit ${a.exitCode}  ${a.decision.label}"

    fun todayAttempts(status: JobStatus): List<JobAttempt> = attemptsOn(status.today.date, status.attempts)
}
