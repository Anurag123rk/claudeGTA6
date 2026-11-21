package com.claudegta6.vicedesk

import android.app.Activity
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File

/** Starts the Python engine once per process and remembers its URL across activity restarts. */
object Engine {
    @Volatile private var url: String? = null

    @Synchronized
    fun start(ctx: Context): String {
        url?.let { return it }
        if (!Python.isStarted()) Python.start(AndroidPlatform(ctx))
        val bundle = unpackAssets(ctx)
        val ws = File(ctx.getExternalFilesDir(null) ?: ctx.filesDir, "ViceDesk").apply { mkdirs() }
        val u = Python.getInstance().getModule("desk.android_main").callAttr(
            "start", ctx.filesDir.absolutePath, ctx.applicationInfo.nativeLibraryDir, ws.absolutePath, bundle.absolutePath
        ).toString()
        url = u
        return u
    }

    /** Copy assets/bundle (pipeline scripts + UI) to real files, once per installed version. */
    private fun unpackAssets(ctx: Context): File {
        val dest = File(ctx.filesDir, "bundle")
        val stamp = File(dest, ".stamp")
        val info = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
        val want = "${info.longVersionCode}-${info.lastUpdateTime}"
        if (stamp.exists() && stamp.readText() == want) return dest
        dest.deleteRecursively()
        copyAsset(ctx, "bundle", dest)
        stamp.writeText(want)
        return dest
    }

    private fun copyAsset(ctx: Context, path: String, target: File) {
        val children = ctx.assets.list(path) ?: emptyArray()
        if (children.isEmpty()) {
            target.parentFile?.mkdirs()
            ctx.assets.open(path).use { input -> target.outputStream().use { input.copyTo(it) } }
        } else {
            target.mkdirs()
            for (c in children) copyAsset(ctx, "$path/$c", File(target, c))
        }
    }
}

class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var splash: TextView
    private var pendingShare: String? = null
    private var loaded = false

    companion object { const val REQ_PICK = 41; const val REQ_LOGIN = 43 }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) // long downloads/encodes keep going
        val bg = Color.parseColor("#140B18")
        web = WebView(this).apply {
            setBackgroundColor(bg)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            addJavascriptInterface(Bridge(), "ViceAndroid")
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                    val host = req.url.host ?: return false
                    if (host == "127.0.0.1" || host == "localhost") return false
                    openExternal(req.url.toString()); return true
                }
                override fun onPageFinished(view: WebView, url: String) {
                    loaded = true
                    pendingShare?.let { deliverShared(it); pendingShare = null }
                }
            }
        }
        splash = TextView(this).apply {
            text = "Vice Desk\n\nStarting the clip engine…"
            setTextColor(Color.parseColor("#F4E9F2")); textSize = 18f
            gravity = Gravity.CENTER; setBackgroundColor(bg)
        }
        val root = FrameLayout(this).apply { setBackgroundColor(bg); addView(web); addView(splash) }
        Insets.applySafeArea(root)  // no overlap with the status bar, notch/cutout, nav bar or keyboard
        setContentView(root)
        handleShare(intent)
        Thread {
            try {
                val url = Engine.start(applicationContext)
                runOnUiThread { splash.visibility = View.GONE; web.loadUrl(url) }
            } catch (e: Throwable) {
                runOnUiThread { splash.text = "The engine could not start:\n\n${e.message}" }
            }
        }.start()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    private fun handleShare(i: Intent?) {
        if (i?.action != Intent.ACTION_SEND) return
        val text = i.getStringExtra(Intent.EXTRA_TEXT) ?: return
        val link = Regex("https?://\\S+").find(text)?.value ?: return
        if (loaded) deliverShared(link) else pendingShare = link
    }

    private fun deliverShared(link: String) =
        web.evaluateJavascript("window.onSharedUrl && window.onSharedUrl(${JSONObject.quote(link)})", null)

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        web.evaluateJavascript("window.onAndroidBack ? window.onAndroidBack() : false") { handled ->
            if (handled != "true") super.onBackPressed()
        }
    }

    private var askedNotifications = false

    /** Android 13+: the progress notification needs permission (the work continues either way). */
    private fun askNotifications() = runOnUiThread {
        if (askedNotifications || android.os.Build.VERSION.SDK_INT < 33) return@runOnUiThread
        askedNotifications = true
        if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 42)
    }

    private fun openExternal(url: String) {
        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } catch (_: Exception) { message("No app can open this link") }
    }

    private fun message(text: String) = runOnUiThread {
        web.evaluateJavascript("window.onAndroidMessage && window.onAndroidMessage(${JSONObject.quote(text)})", null)
    }

    /** Copy a finished clip into Movies/ViceDesk so the gallery, TikTok, Instagram etc. can see it. */
    private fun copyToGallery(path: String): Uri {
        val f = File(path)
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, "vicedesk_${System.currentTimeMillis() / 1000}_${f.name}")
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, Environment.DIRECTORY_MOVIES + "/ViceDesk")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val uri = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("gallery refused the file")
        contentResolver.openOutputStream(uri)!!.use { out -> f.inputStream().use { it.copyTo(out) } }
        values.clear(); values.put(MediaStore.Video.Media.IS_PENDING, 0)
        contentResolver.update(uri, values, null, null)
        return uri
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_LOGIN) {
            val n = data?.getIntExtra("count", 0) ?: 0
            web.evaluateJavascript("window.onCookiesSaved && window.onCookiesSaved($n, ${resultCode == RESULT_OK})", null)
            return
        }
        if (requestCode != REQ_PICK || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        message("Copying the video into Vice Desk…")
        Thread {
            try {
                var name = "picked.mp4"
                contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                    if (c.moveToFirst()) name = c.getString(0) ?: name
                }
                name = name.replace(Regex("[^A-Za-z0-9._-]"), "_")
                val dir = File(getExternalFilesDir(null) ?: filesDir, "ViceDesk/imports").apply { mkdirs() }
                val out = File(dir, name)
                contentResolver.openInputStream(uri)!!.use { input -> out.outputStream().use { input.copyTo(it) } }
                runOnUiThread {
                    web.evaluateJavascript("window.onPickedVideo && window.onPickedVideo(${JSONObject.quote(out.absolutePath)})", null)
                }
            } catch (e: Exception) { message("Could not read that video: ${e.message}") }
        }.start()
    }

    inner class Bridge {
        @JavascriptInterface fun openUrl(url: String) = runOnUiThread { openExternal(url) }

        @JavascriptInterface fun saveToGallery(path: String) {
            Thread {
                try { copyToGallery(path); message("Saved to your gallery (Movies/ViceDesk)") }
                catch (e: Exception) { message("Save failed: ${e.message}") }
            }.start()
        }

        @JavascriptInterface fun shareFile(path: String) {
            Thread {
                try {
                    val uri = copyToGallery(path)
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = "video/mp4"; putExtra(Intent.EXTRA_STREAM, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    runOnUiThread { startActivity(Intent.createChooser(send, "Post clip with…")) }
                } catch (e: Exception) { message("Share failed: ${e.message}") }
            }.start()
        }

        /** Called by the UI with a one-line summary of running work ("" when idle). */
        @JavascriptInterface fun setBusy(text: String) {
            if (text.isNotBlank()) askNotifications()
            EngineService.update(applicationContext, text)
        }

        /** Opens the in-app YouTube sign-in; the cookies it saves fix "Sign in to confirm you're not a bot". */
        @JavascriptInterface fun youtubeLogin() = runOnUiThread {
            @Suppress("DEPRECATION") startActivityForResult(Intent(this@MainActivity, YoutubeLoginActivity::class.java), REQ_LOGIN)
        }

        @JavascriptInterface fun pickVideo() = runOnUiThread {
            val i = Intent(Intent.ACTION_OPEN_DOCUMENT).apply { addCategory(Intent.CATEGORY_OPENABLE); type = "video/*" }
            @Suppress("DEPRECATION") startActivityForResult(i, REQ_PICK)
        }
    }
}
