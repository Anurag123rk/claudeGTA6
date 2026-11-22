package com.claudegta6.vicedesk

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** The phone's own text-to-speech (offline, free), called from Python on a worker thread. Returns "" on success. */
object Speech {
    private var tts: TextToSpeech? = null

    private fun engine(ctx: Context): TextToSpeech? {
        tts?.let { return it }
        val latch = CountDownLatch(1)
        var ok = false
        val t = TextToSpeech(ctx.applicationContext) { status -> ok = status == TextToSpeech.SUCCESS; latch.countDown() }
        if (!latch.await(20, TimeUnit.SECONDS) || !ok) { t.shutdown(); return null }
        t.setLanguage(Locale.US)
        tts = t
        return t
    }

    @JvmStatic
    fun maxChars(): Int = TextToSpeech.getMaxSpeechInputLength()

    @JvmStatic
    @Synchronized
    fun synth(ctx: Context, text: String, path: String): String {
        val t = engine(ctx) ?: return "this phone has no text-to-speech engine (install Speech Recognition & Synthesis by Google)"
        val id = "vd" + System.nanoTime()
        val latch = CountDownLatch(1)
        var err = ""
        t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(u: String?) {}
            override fun onDone(u: String?) { if (u == id) latch.countDown() }
            @Deprecated("Deprecated in Java")
            override fun onError(u: String?) { if (u == id) { err = "speech engine error"; latch.countDown() } }
            override fun onError(u: String?, code: Int) { if (u == id) { err = "speech engine error $code"; latch.countDown() } }
        })
        val f = File(path)
        f.parentFile?.mkdirs()
        if (t.synthesizeToFile(text, Bundle(), f, id) != TextToSpeech.SUCCESS) return "speech engine refused the text"
        if (!latch.await(300, TimeUnit.SECONDS)) return "speech engine timed out"
        return err
    }
}
