package com.stockbot.paper

import com.stockbot.paper.data.ExampleSource
import java.io.File

/** The contract's example JSON files as the unit tests see them: copied by Gradle from docs/android/contract/examples into the test resources. */
object TestExamples {
    private const val DIR = "contract-examples"

    val source = ExampleSource { name ->
        val stream = TestExamples::class.java.classLoader!!.getResourceAsStream("$DIR/$name") ?: error("example file not found: $name")
        stream.bufferedReader().use { it.readText() }
    }

    /** Every example file name. */
    fun names(): List<String> {
        val dir = File(TestExamples::class.java.classLoader!!.getResource(DIR)!!.toURI())
        return dir.listFiles { f -> f.name.endsWith(".json") }!!.map { it.name }.sorted()
    }
}
