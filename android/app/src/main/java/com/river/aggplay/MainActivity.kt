package com.river.aggplay

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/**
 * 主界面 = 服务器管理页(WebView) + 顶部一键开播。
 * 首次启动填服务器地址和访问口令；勾选「打开自动开播」后，
 * 手机小爱同学自定义指令「打开聚合待听」即可让音箱直接开播（免架桥语音触发）。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Api.configured(this)) {
            askServerConfig { finish() }
            return
        }

        val pad = (resources.displayMetrics.density * 8).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xFF101418.toInt())
        }
        val playBtn = android.widget.Button(this).apply {
            text = "▶  在音箱上播放待听队列"
            setOnClickListener {
                Toast.makeText(this@MainActivity, "正在推送…", Toast.LENGTH_SHORT).show()
                Thread {
                    val (ok, body) = Api.post(this@MainActivity, "/api/play", "{}")
                    runOnUiThread {
                        Toast.makeText(this@MainActivity,
                            if (ok) "已推送：音箱即将开播" else "失败：$body",
                            Toast.LENGTH_LONG).show()
                    }
                }.start()
            }
        }
        web = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true   // 管理页把口令存 localStorage
            webViewClient = WebViewClient()
            loadUrl(Api.base(this@MainActivity))
        }
        root.addView(playBtn, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            setMargins(pad, pad, pad, pad / 2)
        })
        root.addView(web)
        setContentView(root)

        // 打开即自动开播（给手机小爱自定义指令用）
        if (Api.prefs(this).getBoolean("autoplay_on_open", false)) {
            Thread { Api.post(this, "/api/play", "{}") }.start()
        }
    }

    private fun askServerConfig(onCancel: () -> Unit) {
        val ctx = this
        val user = EditText(ctx).apply { hint = "http://服务器IP:8094" }
        val pass = EditText(ctx).apply { hint = "访问口令（部署日志/管理页可查）" }
        val box = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            val p = (resources.displayMetrics.density * 16).toInt()
            setPadding(p, p / 2, p, 0)
            addView(user); addView(pass)
        }
        AlertDialog.Builder(ctx)
            .setTitle("连接到聚合服务器")
            .setView(box)
            .setCancelable(false)
            .setPositiveButton("保存") { _, _ ->
                Api.save(ctx, user.text.toString(), pass.text.toString())
                if (!Api.configured(ctx)) { onCancel() } else { recreate() }
            }
            .setNeutralButton("退出") { _, _ -> onCancel() }
            .show()
    }

    override fun onBackPressed() {
        if (this::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
