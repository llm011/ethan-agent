"""对话末尾多图横向排布（3 列等隙裁切填充）三端同步契约。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_web_and_desktop_image_grid_in_sync():
    for base in ("web", "desktop/src"):
        gallery = (ROOT / base / "components/chat/image-gallery.tsx").read_text(encoding="utf-8")
        file_card = (ROOT / base / "components/chat/file-card.tsx").read_text(encoding="utf-8")
        bubble = (ROOT / base / "components/chat/message-bubble.tsx").read_text(encoding="utf-8")
        reading = (ROOT / base / "components/chat/reading-mode.tsx").read_text(encoding="utf-8")
        markdown = (ROOT / base / "components/chat/markdown.tsx").read_text(encoding="utf-8")

        for src in (gallery, file_card):
            assert "grid-cols-3 gap-2" in src
            assert "grid-cols-2 gap-2" in src
            assert "object-cover" in src
            assert "aspect-square" in src
            assert "not-prose" in src

        assert "paths.slice(i * 100, (i + 1) * 100)" in file_card
        assert "export function ImageFileGrid" in file_card
        assert "export function isImageFileCard" in file_card
        assert "ImageFileGrid" in bubble and "isImageFileCard" in bubble
        assert "ImageFileGrid" in reading and "isImageFileCard" in reading
        assert "grid-cols-3" in markdown and "object-cover" in markdown


def test_android_image_file_grid_contract():
    file_card_kt = (
        ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/components/FileCardView.kt"
    ).read_text(encoding="utf-8")
    chat_kt = (
        ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/chat/ChatScreen.kt"
    ).read_text(encoding="utf-8")

    assert "fun ImageFileGrid(" in file_card_kt
    assert "cards.chunked(columns)" in file_card_kt
    assert "Arrangement.spacedBy(6.dp)" in file_card_kt
    assert "ContentScale.Crop" in file_card_kt
    assert "aspectRatio(1f)" in file_card_kt
    assert "suspend fun refreshPath" in file_card_kt
    assert "加载失败，点击重试" in file_card_kt
    assert "scope.launch { refreshPath(card.path) }" in file_card_kt
    assert "ImageFileGrid" in chat_kt and "isImageFileCard" in chat_kt
