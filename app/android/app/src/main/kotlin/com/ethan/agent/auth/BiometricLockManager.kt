package com.ethan.agent.auth

import android.os.Build
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

/**
 * 应用锁：启动时用系统生物识别 / 设备凭据（PIN/密码/图案）解锁。
 *
 * 设计：
 * - 只负责「弹出验证 + 回调结果」，是否启用由 [com.ethan.agent.core.datastore.AppConfig.appLockEnabled] 决定。
 * - 安全级别：优先 **强生物识别** + 设备凭据兜底。弱生物识别（部分 2D 人脸）不作为「应用锁」的凭据。
 * - 无凭据处理（两处语义不同，见评审 #3）：
 *     - **开开关时**（[canAuthenticate]）：设备没有任何可用凭据 → UI 层拦截并提示「请先设锁屏密码」，不打开开关。
 *     - **解锁时**（[authenticate]）：若开关已开但凭据被移除，仍放行，避免把用户永久挡在门外。
 */
object BiometricLockManager {

    /**
     * 本设备可用的验证器组合。
     *
     * `BIOMETRIC_STRONG or DEVICE_CREDENTIAL` 官方仅在 API 30+ 完整支持；
     * API 26–29 该组合会让 BiometricPrompt 抛「Crypto-based authentication not supported」，
     * 故降级为 `BIOMETRIC_WEAK or DEVICE_CREDENTIAL`（老系统上的既有行为，能用锁屏密码兜底）。
     */
    private fun allowedAuthenticators(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            BiometricManager.Authenticators.BIOMETRIC_STRONG or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
        } else {
            BiometricManager.Authenticators.BIOMETRIC_WEAK or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
        }

    /** 设备当前是否可以进行验证（强生物识别或设备凭据）。开开关前用它拦截「无凭据」设备。 */
    fun canAuthenticate(activity: FragmentActivity): Boolean {
        val manager = BiometricManager.from(activity)
        return manager.canAuthenticate(allowedAuthenticators()) == BiometricManager.BIOMETRIC_SUCCESS
    }

    /**
     * 弹出验证。
     * @param onSuccess 验证通过；或设备已无任何凭据（无法锁，放行避免锁死）。
     * @param onFailure 用户取消或多次失败（应保持锁定）。
     */
    fun authenticate(
        activity: FragmentActivity,
        onSuccess: () -> Unit,
        onFailure: () -> Unit,
    ) {
        // 设备无任何凭据 → 无法锁，直接放行（不把用户永久挡在门外）
        if (!canAuthenticate(activity)) {
            onSuccess()
            return
        }

        val executor = ContextCompat.getMainExecutor(activity)
        val prompt = BiometricPrompt(
            activity,
            executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    onSuccess()
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    // 用户主动取消 / 系统关闭 → 保持锁定
                    onFailure()
                }
                // onAuthenticationFailed（单次不匹配）不回调，交给系统继续等待
            },
        )

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("解锁 Ethan")
            .setSubtitle("使用生物识别或设备密码验证身份")
            .setAllowedAuthenticators(allowedAuthenticators())
            .build()

        prompt.authenticate(promptInfo)
    }
}
