package com.ethan.agent.shared

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * 进程级前台/后台信号中转站。
 *
 * 为什么需要它：判断「界面为什么变离线」必须区分两种断线——
 *   - **真断线**：网络切换 / 服务端重启，连接自己断了；
 *   - **被挂起**：App 进了后台，系统冻结进程 / 回收 socket，`onPause` 之后就再也没有
 *     任何回调告诉我们连接没了。
 *
 * 第二种情况下，客户端手里那条 `isStreaming` / `ConnectionState` 是**陈旧**的：
 * 进程醒来时它还在等着一个早就死掉的 socket，界面就一直停在断线态。修法是切回前台时
 * 主动探活 + 重新接流（见 `ChatViewModel.onAppForegrounded`）。
 *
 * 放在 shared（而不是各端 UI 层）的原因：ViewModel 在 commonMain，不能直接碰
 * Android 的 `ProcessLifecycleOwner` 或 iOS 的 `UIApplication` 通知；由各端把平台信号
 * 翻译成这里的 [post] 调用，ViewModel 只订阅这个与平台无关的流。
 */
object AppLifecycleBus {
    private val _foregroundEvents = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val foregroundEvents: SharedFlow<Unit> = _foregroundEvents.asSharedFlow()

    /**
     * 由平台层在「App 回到前台」时调用。
     *
     * 用 [MutableSharedFlow.tryEmit] 而不是挂起发射：这个函数会从 Android 的
     * `ON_START` 回调（主线程）调用，不能被挂起；订阅者慢一拍也不该拖住生命周期回调。
     * `extraBufferCapacity = 1` 保证没有订阅者时不会丢事件，也不会阻塞。
     */
    fun postForeground() {
        _foregroundEvents.tryEmit(Unit)
    }
}
