// A shell, built against PyCharm Community. It uses only long-stable platform API -- JCEF,
// ToolWindowFactory, NotificationGroupManager -- so `sinceBuild` can reach back several releases
// below the version it compiles against.
plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "2.0.21"
    id("org.jetbrains.intellij.platform") version "2.1.0"
}

group = "com.agentdata"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        pycharmCommunity("2024.2.5")
    }
}

kotlin {
    jvmToolchain(17)
}

intellijPlatform {
    // Bytecode instrumentation exists for `@NotNull` checks and for compiling GUI Designer `.form`
    // files. This plugin is Kotlin with no forms, so it buys nothing -- and turning it on drags in
    // a Java compiler dependency and IntelliJ's Ant taskdef, which is what the build actually
    // failed on: "No Java Compiler dependency found" / InstrumentIdeaExtensions not found.
    instrumentCode = false

    pluginConfiguration {
        ideaVersion {
            // 232 is PyCharm 2023.2, the oldest version this was checked against by hand.
            sinceBuild = "232"
            // The plugin API's way of saying "no upper bound" moves between releases; a far-future
            // build number is the spelling that works everywhere and means the same thing in
            // practice. Revisit when it actually approaches.
            untilBuild = "299.*"
        }
    }
}

tasks {
    // Nothing in this plugin talks to a marketplace, and the verifier's IDE downloads are minutes
    // of CI for a shell with no platform-specific behaviour. `buildPlugin` is the artefact.
    buildSearchableOptions { enabled = false }
}
