plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.stockbot.paper"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.stockbot.paper"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0-contract"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    lint {
        abortOnError = true
        warningsAsErrors = false
    }
}

// The example JSON files of the contract are the only copy of the mock data. They live in docs/android/contract/examples and are copied
// (not duplicated in git) into the debug assets and the unit-test resources, under the folder name "contract-examples".
val contractExamplesDir = rootProject.layout.projectDirectory.dir("../docs/android/contract/examples")
val copiedExamples = layout.buildDirectory.dir("generated/contract-examples")
val copyContractExamples = tasks.register<Copy>("copyContractExamples") {
    from(contractExamplesDir) { include("*.json") }
    into(copiedExamples.map { it.dir("contract-examples") })
}
android.sourceSets.getByName("debug").assets.srcDir(copiedExamples)
android.sourceSets.getByName("test").resources.srcDir(copiedExamples)
tasks.configureEach {
    if ((name.startsWith("merge") && name.endsWith("Assets")) || name.endsWith("UnitTestJavaRes") || name.contains("Lint", ignoreCase = true)) {
        dependsOn(copyContractExamples)
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
}
