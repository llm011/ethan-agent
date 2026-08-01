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
 * callback：collect StateFlow，每次新值触发所有已注册的 [observe] 回调。
 *
 * 支持多观察者（list），避免第二次 observe 静默替换第一次。Swift 端用
 * 轻量 ObservableObject wrapper 接入 SwiftUI：
 *
 * ```swift
 * final class ObservableState<T: AnyObject>: ObservableObject {
 *     @Published var value: T
 *     private let wrapper: StateFlowWrapper<T>
 *     private var observer: ((T) -> Void)?
 *     init(_ wrapper: StateFlowWrapper<T>) {
 *         self.wrapper = wrapper
 *         self.value = wrapper.value
 *         observer = wrapper.observe { [weak self] newValue in
 *             DispatchQueue.main.async { self?.value = newValue }
 *         }
 *     }
 *     deinit { wrapper.close() }
 * }
 * ```
 *
 * 线程安全：collect 在 MainScope（主线程）上跑，observe/removeObserver
 * 由 Swift 端在主线程调用，两者同线程，无需同步原语。
 */
class StateFlowWrapper<T : Any>(flow: StateFlow<T>) {

    private val scope = MainScope()

    /** 当前 StateFlow 的值。 */
    var value: T = flow.value
        private set

    private val observers = mutableListOf<(T) -> Unit>()

    init {
        scope.launch {
            flow.collect { newValue ->
                value = newValue
                observers.forEach { it.invoke(newValue) }
            }
        }
    }

    /**
     * 注册值变化回调。注册后立即触发一次（同步推送当前值），让 UI 首帧有数据。
     * 返回回调本身，传给 [removeObserver] 注销。支持多观察者，不会互相替换。
     */
    fun observe(callback: (T) -> Unit): (T) -> Unit {
        observers.add(callback)
        callback(value)
        return callback
    }

    /** 注销 [observe] 返回的回调。 */
    fun removeObserver(callback: (T) -> Unit) {
        observers.remove(callback)
    }

    /** 释放 collect 协程并清空观察者。VM 销毁时调用。 */
    fun close() {
        scope.cancel()
        observers.clear()
    }
}
