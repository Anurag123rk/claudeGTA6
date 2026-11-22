package com.claudegta6.vicedesk

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager

/**
 * Keeps Vice Desk running while a task is active and you switch to another app.
 *
 * Android freezes background apps and cuts their network, which killed downloads half-way. While the UI reports
 * a running task, this foreground service shows a progress notification and holds a CPU wake lock and a Wi-Fi
 * lock; it stops itself when nothing is running.
 */
class EngineService : Service() {
    private var cpu: PowerManager.WakeLock? = null
    private var wifi: WifiManager.WifiLock? = null

    companion object {
        private const val CHANNEL = "work"
        private const val ID = 7
        @Volatile var instance: EngineService? = null

        /** text = what is running (e.g. "Downloading video · 45% · 3.2 MB/s"); null or blank = idle. */
        @JvmStatic
        fun update(ctx: Context, text: String?) {
            val running = instance
            if (text.isNullOrBlank()) {
                running?.stopSelf()
                return
            }
            if (running != null) {
                running.show(text)
                return
            }
            val i = Intent(ctx, EngineService::class.java).putExtra("text", text)
            try {
                ctx.startForegroundService(i)
            } catch (_: Exception) {
                // Android refuses to start it while the app is already in the background; it starts next time.
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Downloads and clip work", NotificationManager.IMPORTANCE_LOW)
            .apply { description = "Shown while Vice Desk downloads or cuts clips in the background" })
        cpu = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ViceDesk:work").apply { setReferenceCounted(false); acquire(6 * 60 * 60 * 1000L) }
        @Suppress("DEPRECATION")
        val mode = if (Build.VERSION.SDK_INT >= 34) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF
        wifi = applicationContext.getSystemService(WifiManager::class.java)
            ?.createWifiLock(mode, "ViceDesk:work")?.apply { setReferenceCounted(false); acquire() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val n = build(intent?.getStringExtra("text") ?: "Working…")
        if (Build.VERSION.SDK_INT >= 29) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(ID, n)
        return START_NOT_STICKY
    }

    fun show(text: String) = getSystemService(NotificationManager::class.java).notify(ID, build(text))

    private fun build(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
        val pct = Regex("(\\d{1,3})%").find(text)?.groupValues?.get(1)?.toIntOrNull()
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Vice Desk is working")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .apply { if (pct != null) setProgress(100, pct.coerceIn(0, 100), false) else setProgress(0, 0, true) }
            .build()
    }

    override fun onDestroy() {
        instance = null
        try { cpu?.release() } catch (_: Exception) {}
        try { wifi?.release() } catch (_: Exception) {}
        super.onDestroy()
    }
}
