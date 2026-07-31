package com.ethan.agent.auth

import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

/**
 * 应用锁：启动时用系统生物识别 / 设备凭据（PIN/密码/图案）解锁。
 *
 * 设计：
 * - 只负责「弹出验证 + 回调结果」，是否启用由 [com.ethan.agent.core.datastore.AppConfig.appLockEnabled] 决定。
 * - 允许的验证方式：强生物识别 + 设备凭据兜底（没有指纹/人脸时可用锁屏密码）。
 * - 设备根本没有任何可用凭据时视为「无需锁」，直接放行，避免把用户永久挡在门外。
 */
object BiometricLockManager {

    /** 设备当前是否可以进行任意一种身份验证（生物识别或设备凭据）。 */
    fun canAuthenticate(activity: FragmentActivity): Boolean {
        val manager = BiometricManager.from(activity)
        val allowed = BiometricManager.Authenticators.BIOMETRIC_WEAK or
            BiometricManager.Authenticators.DEVICE_CREDENTIAL
        return manager.canAuthenticate(allowed) == BiometricManager.BIOMETRIC_SUCCESS
    }

    /**
     * 弹出验证。
     * @param onSuccess 验证通过。
     * @param onFailure 用户取消或多次失败（应保持锁定）。
     */
    fun authenticate(
        activity: FragmentActivity,
        onSuccess: () -> Unit,
        onFailure: () -> Unit,
    ) {
        // 设备无任何凭据 → 无法锁，直接放行
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
            .setAllowedAuthenticators(
                BiometricManager.Authenticators.BIOMETRIC_WEAK or
                    BiometricManager.Authenticators.DEVICE_CREDENTIAL,
            )
            .build()

        prompt.authenticate(promptInfo)
    }
}
