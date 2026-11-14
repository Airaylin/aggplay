package com.river.aggplay

import android.content.ClipboardManager
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/**
 * 剪贴板快投：快捷磁贴点击 → 拉起本透明页（短暂获得焦点，Android 10+ 合法读剪贴板）
 * → 读到内容立即 POST /api/add → finish。
 */
class ClipboardGrabActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Api.configured(this)) {
            Toast.makeText(this, "先打开聚合待听App配置服务器地址", Toast.LENGTH_LONG).show()
            finish(); return
        }
        val cm = getSystemService(ClipboardManager::class.java)
        val text = cm.primaryClip?.getItemAt(0)?.text?.toString().orEmpty().trim()
        if (text.isEmpty()) {
            Toast.makeText(this, "剪贴板是空的", Toast.LENGTH_SHORT).show()
            finish(); return
        }
        val body = "{\"text\":${jsonStr(text)}}"
        Thread {
            val (ok, resp) = Api.post(this, "/api/add", body)
            runOnUiThread {
                val msg = when {
                    ok && "\"added\":0" in resp -> "已在队列里"
                    ok -> "✓ 剪贴板已投递"
                    else -> "投递失败：$resp"
                }
                Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
            }
        }.start()
        finish()
    }

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
