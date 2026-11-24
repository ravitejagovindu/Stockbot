package com.stockbot.paper

import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/** A minimal HTTP/1.1 server on loopback for the tests (plain sockets, so it needs no JDK-internal package). One thread per connection, so a slow answer never blocks the next request. */
class FakeServer(private val handler: (Request, Int) -> Reply) {
    class Request(val method: String, val path: String, val token: String?)

    sealed interface Reply {
        /** Answer with [status] and [body], after waiting [delayMs] (to provoke a client timeout). */
        data class Respond(val status: Int, val body: String, val delayMs: Long = 0, val headers: Map<String, String> = emptyMap()) : Reply

        /** Close the connection without answering (a reset / empty reply). */
        data object Drop : Reply
    }

    private val server = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
    private val counter = AtomicInteger()
    val seen = CopyOnWriteArrayList<Request>()
    val url: String get() = "http://127.0.0.1:${server.localPort}"

    init {
        thread(isDaemon = true) {
            while (!server.isClosed) {
                val socket = try { server.accept() } catch (e: IOException) { break }
                thread(isDaemon = true) { handle(socket) }
            }
        }
    }

    fun stop() {
        server.close()
    }

    private fun handle(socket: Socket) {
        try {
            socket.use { s ->
                val reader = s.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                val requestLine = reader.readLine() ?: return
                val parts = requestLine.split(" ")
                var token: String? = null
                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isEmpty()) break
                    if (line.startsWith("X-Paper-Token:", ignoreCase = true)) token = line.substringAfter(":").trim()
                }
                val req = Request(parts[0], parts[1].substringBefore('?'), token)
                seen.add(req)
                when (val reply = handler(req, counter.incrementAndGet())) {
                    FakeServer.Reply.Drop -> return
                    is FakeServer.Reply.Respond -> {
                        if (reply.delayMs > 0) Thread.sleep(reply.delayMs)
                        val bytes = reply.body.toByteArray(Charsets.UTF_8)
                        val head = StringBuilder("HTTP/1.1 ${reply.status} X\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n")
                        reply.headers.forEach { (k, v) -> head.append("$k: $v\r\n") }
                        head.append("\r\n")
                        s.getOutputStream().apply { write(head.toString().toByteArray(Charsets.ISO_8859_1)); write(bytes); flush() }
                    }
                }
            }
        } catch (e: IOException) {
            // the client gave up (a timeout test): nothing to do
        }
    }
}
