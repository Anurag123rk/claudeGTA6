package com.claudegta6.vicedesk

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import java.io.File

/**
 * "Sign in to YouTube" for the bot check ("Sign in to confirm you're not a bot").
 *
 * You sign in to YouTube in this screen once; Save writes the session's cookies as a Netscape cookies.txt into the
 * app's private config folder, where yt-dlp picks them up for every download and search. Nothing leaves the phone.
 */
class YoutubeLoginActivity : Activity() {
    private lateinit var web: WebView

    companion object {
        const val SIGN_IN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fm.youtube.com%2F"
        private val SESSION = setOf("SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "LOGIN_INFO")

        fun cookieFile(a: Activity) = File(a.filesDir, "config/youtube_cookies.txt")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val bg = Color.parseColor("#140B18")
        CookieManager.getInstance().setAcceptCookie(true)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            // Google refuses sign-in from embedded browsers it recognises ("; wv"); present as regular Chrome
            settings.userAgentString = settings.userAgentString.replace("; wv", "").replace(Regex("Version/\\d+\\.\\d+ "), "")
            webViewClient = WebViewClient()
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            loadUrl(SIGN_IN_URL)
        }
        val hint = TextView(this).apply {
            text = "Sign in to YouTube (a spare account is safest), then tap Save."
            setTextColor(Color.parseColor("#F4E9F2")); textSize = 14f
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val save = Button(this).apply { text = "Save"; setOnClickListener { saveCookies() } }
        val cancel = Button(this).apply { text = "Cancel"; setOnClickListener { setResult(RESULT_CANCELED); finish() } }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(24, 12, 12, 12); setBackgroundColor(bg)
            addView(hint); addView(cancel); addView(save)
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setBackgroundColor(bg)
            addView(bar)
            addView(web, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        Insets.applySafeArea(root)
        setContentView(root)
    }

    private fun saveCookies() {
        val cm = CookieManager.getInstance()
        cm.flush()
        val pairs = LinkedHashMap<String, String>()
        for (url in listOf("https://www.youtube.com", "https://m.youtube.com", "https://youtube.com")) {
            (cm.getCookie(url) ?: "").split(";").map { it.trim() }.filter { it.contains("=") }.forEach {
                val k = it.substringBefore("="); val v = it.substringAfter("=")
                if (k.isNotBlank()) pairs[k] = v
            }
        }
        if (pairs.keys.none { it in SESSION }) {
            Toast.makeText(this, "Not signed in yet: finish signing in to YouTube, then tap Save.", Toast.LENGTH_LONG).show()
            return
        }
        val expires = System.currentTimeMillis() / 1000 + 180L * 24 * 3600
        val sb = StringBuilder("# Netscape HTTP Cookie File\n# written by Vice Desk (in-app YouTube sign-in)\n")
        for ((k, v) in pairs) sb.append(".youtube.com\tTRUE\t/\tTRUE\t$expires\t$k\t$v\n")
        val f = cookieFile(this)
        f.parentFile?.mkdirs()
        f.writeText(sb.toString())
        setResult(RESULT_OK, intent.putExtra("count", pairs.size))
        finish()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
