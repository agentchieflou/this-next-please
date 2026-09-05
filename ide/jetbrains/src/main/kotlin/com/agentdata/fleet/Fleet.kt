package com.agentdata.fleet

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.nio.charset.StandardCharsets

/**
 * The whole of this shell's knowledge of the fleet: where `serve.json` is, how to ping, how to
 * start the server, how to read the event stream.
 *
 * Deliberately no more than that. Which agents need a person, what to say about them and when to
 * stay quiet are decided by `agentdata/fleet/notify.py`; a second implementation in Kotlin would
 * eventually disagree with the tiles it sits beside, and the operator would have no way to tell
 * which was right.
 */
object Fleet {
    const val CONTRACT = 1

    data class Record(val url: String, val token: String, val port: Int)

    data class Ping(val service: String, val version: String, val contract: Int)

    data class Note(
        val repo: String,
        val severity: String,
        val title: String,
        val body: String
    )

    /** `$AGENTDATA_FLEET_DIR`, else `~/.agentdata/fleet` -- the same rule the Python side uses. */
    fun fleetDir(): File {
        val override = System.getenv("AGENTDATA_FLEET_DIR")
        if (!override.isNullOrBlank()) return File(override.trim())
        return File(File(System.getProperty("user.home"), ".agentdata"), "fleet")
    }

    fun readRecord(): Record? = try {
        val text = File(fleetDir(), "serve.json").readText(StandardCharsets.UTF_8)
        val json = JsonParser.parseString(text).asJsonObject
        val port = json.get("port")?.asInt ?: 0
        if (port > 0) {
            Record(json.get("url").asString, json.get("token").asString, port)
        } else {
            null
        }
    } catch (e: Exception) {
        null
    }

    private fun get(url: String, timeoutMs: Int): String? = try {
        val connection = URI(url).toURL().openConnection() as HttpURLConnection
        connection.connectTimeout = timeoutMs
        connection.readTimeout = timeoutMs
        connection.inputStream.use { it.readBytes().toString(StandardCharsets.UTF_8) }
    } catch (e: Exception) {
        null
    }

    /** Is *our* dashboard on that port? Not "is the port open" -- something else may hold it. */
    fun ping(port: Int, timeoutMs: Int = 2000): Ping? {
        val body = get("http://127.0.0.1:$port/api/ping", timeoutMs) ?: return null
        return try {
            val json = JsonParser.parseString(body).asJsonObject
            if (json.get("service")?.asString != "ad-fleet") {
                null
            } else {
                Ping(
                    "ad-fleet",
                    json.get("version")?.asString ?: "",
                    json.get("contract")?.asInt ?: 0
                )
            }
        } catch (e: Exception) {
            null
        }
    }

    /** The record of a dashboard that is actually answering. A stale file is not a running one. */
    fun running(): Record? {
        val record = readRecord() ?: return null
        return if (ping(record.port) != null) record else null
    }

    /**
     * Start `ad-fleet serve` and wait for it to answer.
     *
     * `ad-fleet` first, `python -m agentdata fleet` second: the console scripts are frequently not
     * on PATH, which is the single most common way this package looks broken when it is merely
     * unfound. Detached, because closing the IDE should not take the dashboard down -- the other
     * shells attach to the same server.
     */
    fun startServer(port: Int, configured: String): Record {
        val attempts = mutableListOf<List<String>>()
        if (configured.isNotBlank()) {
            attempts.add(configured.trim().split(Regex("\\s+")) + listOf("serve", "--port", port.toString()))
        }
        attempts.add(listOf("ad-fleet", "serve", "--port", port.toString()))
        val python = if (System.getProperty("os.name").startsWith("Windows")) "py" else "python3"
        attempts.add(listOf(python, "-m", "agentdata", "fleet", "serve", "--port", port.toString()))

        var last = ""
        for (argv in attempts) {
            try {
                ProcessBuilder(argv).redirectErrorStream(true).start()
            } catch (e: Exception) {
                last = e.message ?: argv.first()
                continue
            }
            val deadline = System.currentTimeMillis() + 20_000
            while (System.currentTimeMillis() < deadline) {
                running()?.let { return it }
                Thread.sleep(300)
            }
            last = "${argv.first()} did not start answering on $port"
        }
        throw IllegalStateException(
            "could not start the fleet dashboard ($last). Run `ad-fleet serve` in a terminal to " +
                "see why, or set the command in Settings."
        )
    }

    /** How many agents need a person, straight from the server's own answer rather than a rule. */
    fun needingHuman(record: Record): Int {
        val body = get(
            "http://127.0.0.1:${record.port}/api/fleet?t=${record.token}", 5000
        ) ?: return 0
        return try {
            JsonParser.parseString(body).asJsonObject
                .getAsJsonArray("repos")
                .count { it.asJsonObject.get("needs_human")?.asBoolean == true }
        } catch (e: Exception) {
            0
        }
    }

    fun startAgent(record: Record, repo: String, ticket: String): Pair<Boolean, String> {
        return try {
            val connection = URI("http://127.0.0.1:${record.port}/api/start?t=${record.token}")
                .toURL().openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = 5000
            connection.readTimeout = 60_000
            connection.setRequestProperty("Content-Type", "application/json")
            val payload = Gson().toJson(mapOf("repo" to repo, "ticket" to ticket))
            connection.outputStream.use { it.write(payload.toByteArray(StandardCharsets.UTF_8)) }
            val stream = if (connection.responseCode < 400) connection.inputStream else connection.errorStream
            val answer = stream.use { it.readBytes().toString(StandardCharsets.UTF_8) }
            val json = JsonParser.parseString(answer).asJsonObject
            if (json.get("ok")?.asBoolean == true) {
                true to repo
            } else {
                // The server's refusal verbatim: it already says why and what would fix it, and
                // rewording it here would give the operator two explanations of one rule.
                false to listOfNotNull(
                    json.get("error")?.asString,
                    json.get("hint")?.asString
                ).joinToString(" — ")
            }
        } catch (e: Exception) {
            false to (e.message ?: "the dashboard did not answer")
        }
    }

    fun repos(record: Record): List<Pair<String, String>> {
        val body = get("http://127.0.0.1:${record.port}/api/fleet?t=${record.token}", 5000)
            ?: return emptyList()
        return try {
            JsonParser.parseString(body).asJsonObject.getAsJsonArray("repos").map {
                val o: JsonObject = it.asJsonObject
                o.get("repo").asString to (o.get("path")?.asString ?: "")
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    /**
     * Read the server's event stream and call back on notifications.
     *
     * A hand-rolled SSE reader: the format is a few lines and a blank, and a dependency here is one
     * more thing to audit for a corporate install of an unsigned plugin.
     */
    class Notifications(
        private val record: Record,
        private val onNote: (Note) -> Unit
    ) : Runnable {
        @Volatile
        private var stopped = false

        fun stop() {
            stopped = true
        }

        override fun run() {
            while (!stopped) {
                try {
                    val connection = URI("http://127.0.0.1:${record.port}/api/events?t=${record.token}")
                        .toURL().openConnection() as HttpURLConnection
                    connection.connectTimeout = 5000
                    connection.readTimeout = 0            // the stream is meant to stay open
                    BufferedReader(InputStreamReader(connection.inputStream, StandardCharsets.UTF_8)).use { reader ->
                        var event = "message"
                        val data = StringBuilder()
                        while (!stopped) {
                            val line = reader.readLine() ?: break
                            when {
                                line.startsWith("event: ") -> event = line.substring(7).trim()
                                line.startsWith("data: ") -> data.append(line.substring(6))
                                line.isEmpty() -> {
                                    if (event == "notify" && data.isNotEmpty()) {
                                        parse(data.toString())?.let(onNote)
                                    }
                                    event = "message"
                                    data.setLength(0)
                                }
                            }
                        }
                    }
                } catch (e: Exception) {
                    // The dashboard was stopped, or the machine slept. Neither is an error worth a
                    // balloon; the reconnect below is the whole response.
                }
                if (!stopped) Thread.sleep(3000)
            }
        }

        private fun parse(json: String): Note? = try {
            val o = JsonParser.parseString(json).asJsonObject
            Note(
                o.get("repo")?.asString ?: "",
                o.get("severity")?.asString ?: "info",
                o.get("title")?.asString ?: "",
                o.get("body")?.asString ?: ""
            )
        } catch (e: Exception) {
            null                                          // a frame from a newer server; ignore it
        }
    }
}
