package com.ethan.agent.shared

import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

/**
 * 将 Kotlin [StateFlow] 桥接为 iOS 端可观察的对象。
 *
 * 不继承 NSObject（KVO 的 willChange/didChange 在 Kotlin/Native 2.1 有重载
 * 解析问题，NotificationCenter 的 API 互操作也有诸多坑），改用纯 Kotlin
 * callback：collect StateFlow，每次新值触发 [onChange] 回调。
 *
 * Swift 端用一个轻量 ObservableObject wrapper 即可接入 SwiftUI：
 *
 * ```swift
 * // 放在 iOS 工程的 Shared/ 目录
 * final class ObservableState<T: AnyObject>: ObservableObject {
 *     @Published var value: T
 *     private let wrapper: StateFlowWrapper<T>
 *     init(_ wrapper: StateFlowWrapper<T>) {
 *         self.wrapper = wrapper
 *         self.value = wrapper.value
 *         wrapper.observe { [weak self] newValue in
 *             DispatchQueue.main.async { self?.value = newValue }
 *         }
 *     }
 *     deinit { wrapper.close() }
 * }
 *
 * // 在 View 里使用
 * @StateObject private var state = ObservableState(
 *     StateFlowWrapper(flow: IosViewModels.sharedChatViewModel(sessionId: nil).state)
 * )
 * // state.value.xxx
 * ```
 *
 * 持续在 MainScope 上 collect。VM 销毁时调 [close] 释放协程，避免泄漏。
 */
class StateFlowWrapper<T : Any>(flow: StateFlow<T>) {

    private val scope = MainScope()

    /** 当前 StateFlow 的值。 */
    var value: T = flow.value
        private set

    private var onChange: ((T) -> Unit)? = null

    init {
        scope.launch {
            flow.collect { newValue ->
                value = newValue
                onChange?.invoke(newValue)
            }
        }
    }

    /**
     * 注册值变化回调。注册后立即触发一次（同步推送当前值），让 UI 首帧有数据。
     * 后续每次 StateFlow 发射新值时异步触发（在 collect 所在线程，通常是 Default）。
     */
    fun observe(callback: (T) -> Unit) {
        onChange = callback
        callback(value)
    }

    /** 释放 collect 协程。VM 销毁时调用。 */
    fun close() {
        scope.cancel()
    }
}
