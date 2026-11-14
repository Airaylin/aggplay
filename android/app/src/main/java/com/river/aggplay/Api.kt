package com.river.aggplay

import android.content.Context
import java.net.HttpURLConnection
import java.net.URL

/** 极简 API 客户端：服务器地址+口令存 SharedPreferences，HttpURLConnection 零依赖。 */
object Api {

    fun prefs(ctx: Context) = ctx.getSharedPreferences("aggplay", Context.MODE_PRIVATE)

    fun base(ctx: Context): String =
        prefs(ctx).getString("base", "")!!.trimEnd('/')

    fun save(ctx: Context, base: String, pass: String) {
        prefs(ctx).edit()
            .putString("base", base.trim().trimEnd('/'))
            .putString("pass", pass.trim())
            .apply()
    }

    fun configured(ctx: Context): Boolean =
        base(ctx).startsWith("http")

    /** POST JSON，返回 (httpOk, body)；任何网络错误返回 (false, 错误文本)。 */
    fun post(ctx: Context, path: String, json: String): Pair<Boolean, String> {
        val b = base(ctx)
        if (!b.startsWith("http")) return false to "还没配置服务器地址"
        return try {
            val conn = URL(b + path).openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 15000
            conn.readTimeout = 30000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("X-Admin-Pass", prefs(ctx).getString("pass", ""))
            conn.outputStream.use { it.write(json.toByteArray()) }
            val body = conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
            (conn.responseCode in 200..299) to body
        } catch (e: Exception) {
            false to (e.message ?: e.toString())
        }
    }
}
