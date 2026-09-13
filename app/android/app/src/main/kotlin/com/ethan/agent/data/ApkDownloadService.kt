package com.ethan.agent.data

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import com.ethan.agent.MainActivity
import com.ethan.agent.R
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.shared.update.DownloadProgressBus
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * 后台下载 APK 的前台服务。
 *
 * **为什么是前台服务**：用户点了「更新」之后切到别的 app 或息屏是很自然的动作，
 * 而在后台的普通协程会被系统在几十秒内冻住/杀掉，表现就是「进度卡住不动」。
 * 挂在 dataSync 类型的前台服务上，系统就不会动它，且通知栏能显示进度。
 *
 * **为什么不用 WorkManager**：它是「可延迟、满足约束后再跑」的语义 —— 对
 * 「用户正盯着进度条等」这种即时任务是错配，而且会引入一个新依赖。
 *
 * 服务只负责**编排 + 通知**：真正的下载在 [ApkDownloader]，失败决策在
 * [com.ethan.agent.shared.update.DownloadPlan]。
 */
class ApkDownloadService : Service() {

    companion object {
        private const val CHANNEL_ID = "apk_download"
        /** 稳定 id：下载过程中反复 notify 是「更新同一条」，不会堆一屏通知。 */
        private const val NOTIFICATION_ID = 0xE7A0
        private const val EXTRA_VERSION = "version"
        private const val EXTRA_URLS = "urls"
        private const val EXTRA_SHA256 = "sha256"
        private const val EXTRA_SIZE = "size"

        /** 通知栏只留一条「下载失败」的文案，原因本身对用户没什么可操作性。 */
        /**
         * 所有候选源都试过且都失败时的文案。
         *
         * 这里**不再写「点按重试」**：弹窗里已经有一个「重试」按钮，正文再让用户
         * 点一次是重复的。改成说明「几个源都试过了」，让用户知道不是只试了一个地址
         * —— 这正是这次加固要传达的信息（多源降级已经跑过了）。
         */
        private const val FAILED_TEXT = "下载失败：已尝试所有下载源，请检查网络后重试"

        fun start(
            context: Context,
            version: String,
            urls: List<String>,
            sha256: String?,
            sizeBytes: Long,
        ) {
            val intent = Intent(context, ApkDownloadService::class.java).apply {
                putExtra(EXTRA_VERSION, version)
                putStringArrayListExtra(EXTRA_URLS, ArrayList(urls))
                putExtra(EXTRA_SHA256, sha256)
                putExtra(EXTRA_SIZE, sizeBytes)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, ApkDownloadService::class.java))
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var downloadJob: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        val version = intent.getStringExtra(EXTRA_VERSION).orEmpty()
        val urls = intent.getStringArrayListExtra(EXTRA_URLS).orEmpty()
        val sha256 = intent.getStringExtra(EXTRA_SHA256)
        val sizeBytes = intent.getLongExtra(EXTRA_SIZE, 0L)

        if (urls.isEmpty()) {
            stopSelf()
            return START_NOT_STICKY
        }

        // 必须先 startForeground 再做耗时工作：Android 要求在 startForegroundService
        // 之后的 5 秒内调用它，否则直接 ANR/崩溃。所以这里用一个 0% 的通知先占位。
        startForegroundCompat(0)

        // 重复 start（用户连点）时先取消上一次，避免两个协程同时写同一个 `.part`
        downloadJob?.cancel()
        downloadJob = scope.launch {
            DownloadProgressBus.update(DownloadProgressBus.DownloadStatus.Running(0))

            val downloader = ApkDownloader(applicationContext)
            val file = downloader.download(
                urls = urls,
                expectedSha256 = sha256,
                expectedSize = sizeBytes,
                onProgress = { progress ->
                    DownloadProgressBus.update(DownloadProgressBus.DownloadStatus.Running(progress))
                    notifyProgress(progress)
                },
            )

            if (file == null) {
                DownloadProgressBus.update(
                    DownloadProgressBus.DownloadStatus.Failed(FAILED_TEXT)
                )
                notifyFailed()
            } else {
                DownloadProgressBus.update(DownloadProgressBus.DownloadStatus.Downloaded)
                notifyDownloaded()
            }
            // 下载结束就退到后台 —— APK 已在磁盘上，安装由 Activity 触发。
            stopForegroundCompat()
            stopSelf()
        }

        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    // ── 通知 ────────────────────────────────────────────────────────────────

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "应用更新",
            // LOW：不要声音、不要横幅。下载进度用默认优先级会不停响，
            // 而且它就在通知栏里滚数字，用户低头看一眼就知道了。
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "下载应用更新时的进度提示"
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
    }

    private fun buildNotification(progress: Int, text: String, ongoing: Boolean): Notification {
        val tapIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            // smallIcon 必须是单色 alpha 剪影，用 launcher icon 会渲染成一坨白块
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle("正在下载更新")
            .setContentText(text)
            .setProgress(100, progress, progress <= 0)
            .setOngoing(ongoing)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(tapIntent)
            .build()
    }

    private fun notifyProgress(progress: Int) {
        notify(buildNotification(progress, "$progress%", ongoing = true))
    }

    private fun notifyDownloaded() {
        notify(
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_download)
                .setContentTitle("下载完成")
                .setContentText("点按继续安装")
                .setOngoing(false)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setContentIntent(
                    PendingIntent.getActivity(
                        this,
                        0,
                        Intent(this, MainActivity::class.java).apply {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                        },
                        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                    )
                )
                .build()
        )
    }

    private fun notifyFailed() {
        notify(
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_download)
                .setContentTitle("更新下载失败")
                .setContentText(FAILED_TEXT)
                .setOngoing(false)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build()
        )
    }

    /**
     * `POST_NOTIFICATIONS` 被用户拒绝是**完全正常的**（API 33+ 默认要问）：此时
     * 通知不会显示，但前台服务和下载本身照常工作。所以这里静默吞掉
     * `SecurityException`，绝不能让「用户不想要通知」变成「更新装不了」。
     */
    private fun notify(notification: Notification) {
        runCatching {
            NotificationManagerCompat.from(this).notify(NOTIFICATION_ID, notification)
        }
    }

    private fun startForegroundCompat(progress: Int) {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        runCatching {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                buildNotification(progress, "准备中…", ongoing = true),
                type,
            )
        }
    }

    private fun stopForegroundCompat() {
        runCatching {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_DETACH)
        }
    }
}
