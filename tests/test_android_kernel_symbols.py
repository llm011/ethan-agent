r"""Android 端内核/语音功能的符号一致性检查。

## 为什么要这个测试

Android 没有可用的 SDK 环境（本机只有 platform-tools），跑不了 `gradlew compile`。
但不能因此就"写完不管"——Kotlin 的类型错误只会在编译期暴露，等到用户装 APK
才发现就太晚了。

所以做静态校验：新增的模型类、API 方法、Composable 引用必须能互相对应。
这不能替代编译，但能抓住最常见的一类错误：**引用了不存在的类/方法名**。

## 背景

Android 端的数据链路和 web/desktop 完全不同：
  Ktor EthanApiService → EthanRepository → SettingsViewModel → Compose
每一层都要手动加方法，漏一层就是编译错误。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "app/android/core/model/src/commonMain/kotlin/com/ethan/agent/core/model/KernelVoice.kt"
API = ROOT / "app/android/core/network/src/commonMain/kotlin/com/ethan/agent/core/network/EthanApiService.kt"
REPO = ROOT / "app/android/shared/src/commonMain/kotlin/com/ethan/agent/shared/EthanRepository.kt"
VM = ROOT / "app/android/shared/src/commonMain/kotlin/com/ethan/agent/shared/viewmodel/SettingsViewModel.kt"
KERNEL_UI = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/settings/KernelSettingsScreen.kt"
VOICE_UI = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/settings/VoiceSettingsScreen.kt"


def _declared_models() -> set[str]:
    src = MODEL.read_text(encoding="utf-8")
    return set(re.findall(r"^data class (\w+)", src, re.M))


def test_all_files_exist():
    for p in (MODEL, API, REPO, VM, KERNEL_UI, VOICE_UI):
        assert p.exists(), f"缺少文件：{p}"


def test_model_classes_declared():
    names = _declared_models()
    for required in (
        "KernelInfoDto", "KernelsResponse", "KernelSelectRequest",
        "VoiceBackendsResponse", "VoiceBackendDto", "VoiceSelectRequest",
    ):
        assert required in names, f"模型类 {required} 未声明"


# 本次新增的功能相关模型（不是文件里的全部 import——其他 DTO 定义在别的文件）
_NEW_MODELS = {
    "KernelInfoDto", "KernelsResponse", "KernelSelectRequest", "KernelSelectResponse",
    "KernelCapabilitiesDto", "VoiceBackendsResponse", "VoiceBackendDto", "VoiceCheckDto",
    "VoiceSelectRequest", "VoiceSelectResponse", "VoiceCurrentDto", "VoicePlatformDto",
}


def test_every_model_used_is_declared():
    """新增代码引用的模型类必须真的存在。

    这条直接对应「漏声明一个 DTO → Kotlin 编译失败」。
    只校验本次涉及的模型名——文件里其它 import 属于既有功能，不该在这里断言。
    """
    declared = _declared_models()
    for path in (API, REPO, VM, KERNEL_UI, VOICE_UI):
        src = path.read_text(encoding="utf-8")
        imports = set(re.findall(r"import com\.ethan\.agent\.core\.model\.(\w+)", src))
        relevant = imports & _NEW_MODELS
        missing = [i for i in relevant if i not in declared]
        assert not missing, f"{path.name} 引用了不存在的模型：{missing}"


def test_api_exposes_kernel_and_voice_methods():
    src = API.read_text(encoding="utf-8")
    for method in ("getKernels", "selectKernel", "getVoiceBackends", "selectVoiceBackend"):
        assert f"suspend fun {method}(" in src, f"EthanApiService 缺少 {method}"
        assert 'url("kernels' in src or 'url("tts' in src


def test_repository_forwards_every_method():
    """Repository 必须透传 API 层的每个新方法，漏一个 ViewModel 就调不到。"""
    api_src = API.read_text(encoding="utf-8")
    repo_src = REPO.read_text(encoding="utf-8")
    for method in ("getKernels", "selectKernel", "getVoiceBackends", "selectVoiceBackend"):
        assert f"suspend fun {method}(" in api_src
        assert f"suspend fun {method}(" in repo_src, f"EthanRepository 没透传 {method}"
        assert f"api.{method}(" in repo_src, f"Repository.{method} 没调到 api"


def test_viewmodel_wires_tabs_and_loaders():
    src = VM.read_text(encoding="utf-8")
    # 枚举要有这两个 Tab
    assert "Kernel, Voice," in src or "Kernel," in src
    # 切 Tab 时触发加载
    assert "SettingsTab.Kernel ->" in src
    assert "SettingsTab.Voice ->" in src
    # state 要能承载数据
    assert "val kernels:" in src
    assert "val voiceBackends:" in src
    # 方法要存在
    for m in ("fun loadKernels", "fun selectKernel", "fun loadVoiceBackends", "fun selectVoiceBackend"):
        assert m in src, f"SettingsViewModel 缺少 {m}"


def test_settings_screen_renders_both_tabs():
    src = (ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/settings/SettingsScreen.kt").read_text(
        encoding="utf-8"
    )
    assert "SettingsTab.Kernel ->" in src, "设置页没有渲染内核 Tab"
    assert "SettingsTab.Voice ->" in src, "设置页没有渲染语音 Tab"
    # 回调参数要存在（默认值兜住既有调用方）
    assert "onSelectKernel:" in src
    assert "onSelectVoice:" in src


def test_app_wires_viewmodel_callbacks():
    src = (ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/EthanApp.kt").read_text(encoding="utf-8")
    for cb in ("onSelectKernel", "onRefreshKernels", "onSelectVoice", "onRefreshVoice"):
        assert f"{cb} = vm::" in src, f"EthanApp 没接 {cb}"


def test_ui_shows_tool_sharing_capability():
    """界面上必须体现「能否共享 Ethan 工具」——这是判断内核价值的关键。"""
    src = KERNEL_UI.read_text(encoding="utf-8")
    assert "sharesEthanTools" in src
    assert "可用 Ethan 的工具" in src
    assert "仅自带工具" in src
    # 不能共享时要展示原因
    assert "sharesEthanToolsReason" in src
