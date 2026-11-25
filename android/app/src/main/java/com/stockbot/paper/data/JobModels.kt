package com.stockbot.paper.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import java.time.LocalDate

/*
 * GET /v1/job (contract v1.1, additive): the daily job's status. Read-only; nothing here can start, retry or stop a job.
 * Timestamps are ISO 8601 with +05:30 and stay text until they are shown (see format/JobFormat.kt).
 */

/** One state of the daily job for a day. An unknown value from a newer server becomes [ALERT], shown neutrally; it never crashes. */
@Serializable(with = JobStateSerializer::class)
enum class JobState { DONE, RUNNING, RETRYING, NO_FILE, ALERT, WAITING, WEEKEND }

object JobStateSerializer : SafeEnumSerializer<JobState>(JobState.entries.toTypedArray(), JobState.ALERT)

/** What the service decided after an attempt. The JSON values are lower case ("catch-up" has a dash); an unknown one becomes [ALERT]. */
@Serializable(with = JobDecisionSerializer::class)
enum class JobDecision(val wire: String, val label: String) {
    DONE("done", "Done"),
    RETRY("retry", "Retry"),
    STOPPED("stopped", "Stopped"),
    ALERT("alert", "Alert"),
    CATCH_UP("catch-up", "Catch-up"),
}

object JobDecisionSerializer : KSerializer<JobDecision> {
    override val descriptor = PrimitiveSerialDescriptor("JobDecision", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): JobDecision {
        val s = decoder.decodeString()
        return JobDecision.entries.firstOrNull { it.wire == s } ?: JobDecision.ALERT
    }

    override fun serialize(encoder: Encoder, value: JobDecision) = encoder.encodeString(value.wire)
}

@Serializable
data class JobService(
    val running: Boolean,
    val pid: Int?,
    val startedAt: String?,
)

@Serializable
data class JobToday(
    @Serializable(with = LocalDateSerializer::class) val date: LocalDate,
    val state: JobState,
    val attempts: Int,
    val lastAttemptAt: String?,
    val lastExitCode: Int?,
    /** One plain sentence. */
    val message: String,
)

@Serializable
data class JobData(
    @Serializable(with = LocalDateSerializer::class) val latestSealedDate: LocalDate?,
    @Serializable(with = LocalDateSerializer::class) val expectedAsOf: LocalDate,
)

@Serializable
data class JobDay(
    @Serializable(with = LocalDateSerializer::class) val date: LocalDate,
    val state: JobState,
    val attempts: Int,
    val finishedAt: String?,
    val lastExitCode: Int?,
)

@Serializable
data class JobAttempt(
    val at: String,
    val exitCode: Int,
    val decision: JobDecision,
)

@Serializable
data class JobStatus(
    override val apiVersion: String,
    @Serializable(with = LocalDateSerializer::class) override val dataAsOf: LocalDate,
    @Serializable(with = LocalDateSerializer::class) override val expectedAsOf: LocalDate,
    override val generatedAt: String,
    val service: JobService,
    /** The next attempt; null when the day is done or over, a job is running, or the service is off. */
    val nextAttemptAt: String?,
    val today: JobToday,
    val data: JobData,
    /** Up to 10 days, oldest first, today last. */
    val history: List<JobDay>,
    /** The last 20 attempts and catch-ups, newest first. */
    val attempts: List<JobAttempt>,
) : Envelope

/** Mock scenarios for the Job screen (debug menu). Each is an example file of the contract. */
enum class JobScenario(val label: String, val file: String) {
    DONE("Done", "job.json"),
    RUNNING("Running", "job_running.json"),
    RETRYING("Retrying", "job_retrying.json"),
    NO_FILE("No file (holiday)", "job_no_file.json"),
    ALERT("Alert", "job_alert.json"),
    SERVICE_OFF("Service off", "job_service_off.json"),
}
