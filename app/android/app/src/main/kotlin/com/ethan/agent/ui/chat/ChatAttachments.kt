package com.ethan.agent.ui.chat

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File

/**
 * 取分享进来 URI 的显示文件名。
 *
 * content:// URI 的 lastPathSegment 往往是 document id（如 "image:1234"），
 * 直接用会得到很怪的文件名，所以优先查 [OpenableColumns.DISPLAY_NAME]，
 * 查不到再退回 lastPathSegment，最后兜底 "shared_file"。
 */
/**
 * 把 URI 内容复制到 cacheDir 的唯一临时文件再上传。
 *
 * 用 [File.createTempFile] 而非「cacheDir/原文件名」：原文件名会让同名分享互相覆盖
 * （两次分享 photo.jpg 会踩同一个文件）。保留原扩展名方便后端识别类型；
 * 展示给用户的文件名仍用 [displayName]。临时文件在上传结束后由 ViewModel 删除。
 */
internal fun copyToTempAndUpload(
    context: Context,
    uri: Uri,
    displayName: String,
    onUpload: (ByteArray, String) -> Unit,
) {
    runCatching {
        // onUpload 接 ByteArray，无需落地临时文件——直接从 InputStream 读 bytes，
        // 避免旧实现中 temp 文件在成功路径不删除导致 cacheDir 泄漏。
        context.contentResolver.openInputStream(uri)?.use { input ->
            onUpload(input.readBytes(), displayName)
        }
    }
}

/** 图片专用：读 bytes 转 base64 dataUrl，走 addImage 而非 uploadAttachment */
internal fun copyAndAddImage(
    context: Context,
    uri: Uri,
    displayName: String,
    onAddImage: (dataUrl: String, base64Data: String, mediaType: String, filename: String) -> Unit,
) {
    runCatching {
        context.contentResolver.openInputStream(uri)?.use { input ->
            val bytes = input.readBytes()
            // 从 URI 推断 MIME type，默认 image/png
            val mediaType = context.contentResolver.getType(uri) ?: "image/png"
            val base64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
            val dataUrl = "data:$mediaType;base64,$base64"
            onAddImage(dataUrl, base64, mediaType, displayName)
        }
    }
}

/** 从 content Uri 里取显示文件名（聊天页附件与设置页头像共用）。 */
internal fun queryDisplayName(context: Context, uri: Uri): String {
    if (uri.scheme == "content") {
        runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0 && cursor.moveToFirst()) {
                        cursor.getString(idx)?.takeIf { it.isNotBlank() }?.let { return it }
                    }
                }
        }
    }
    return uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "shared_file"
}
