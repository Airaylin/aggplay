package com.river.aggplay

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/** 分享接收：B站/网易云等 App 点「分享 → 聚合待听」即投递到服务器队列。 */
class ShareActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = when (intent?.action) {
            Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)
            else -> null
        }
        if (text.isNullOrBlank()) {
            Toast.makeText(this, "没有可投递的内容", Toast.LENGTH_SHORT).show()
            finish(); return
        }
        if (!Api.configured(this)) {
            Toast.makeText(this, "先打开聚合待听App配置服务器地址", Toast.LENGTH_LONG).show()
            finish(); return
        }
        val body = "{\"text\":${jsonStr(text)}}"
        Thread {
            val (ok, resp) = Api.post(this, "/api/add", body)
            runOnUiThread {
                val msg = when {
                    ok && "\"added\":0" in resp -> "已在队列里，不用重复投递"
                    ok -> "✓ 已加入待听队列"
                    else -> "投递失败：$resp"
                }
                Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
            }
        }.start()
        finish()
    }

    /** 最小 JSON 字符串转义。 */
    private fun jsonStr(s: String): String = buildString {
        append('"')
        for (c in s) when (c) {
            '"' -> append("\\\"")
            '\\' -> append("\\\\")
            '\n' -> append("\\n")
            '\r' -> append("\\r")
            '\t' -> append("\\t")
            else -> if (c.code < 0x20) append("\\u%04x".format(c.code)) else append(c)
        }
        append('"')
    }
}
