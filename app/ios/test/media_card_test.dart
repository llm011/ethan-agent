import 'package:ethan_ios/models/app_models.dart';
import 'package:flutter_test/flutter_test.dart';

/// 深度听书交付的音频卡片在 iOS 上曾经是死卡：MediaCard 不认识 mp3，
/// 于是落到「已交付文件」的通用卡片（无 onTap），既不能播也不能下载。
/// 这里锁住分类：音频必须被 isAudio 认出来，而且不能把图片/视频误判成音频。
void main() {
  MediaCard card({String path = '', String kind = '', String mime = ''}) =>
      MediaCard(type: 'file', path: path, kind: kind, mime: mime);

  test('深度听书交付的 mp3/m4a 被识别为音频', () {
    expect(card(path: '/Users/x/out/final.mp3', kind: 'mp3').isAudio, isTrue);
    expect(
        card(path: '/Users/x/out/book.m4a', kind: 'm4a').isAudio, isTrue);
    // 后端卡片 kind 走扩展名，path 缺失时（历史消息只留 kind）也要认出来
    expect(card(kind: 'mp3').isAudio, isTrue);
  });

  test('audio/ mime 也算音频（扩展名缺失时兜底）', () {
    expect(card(path: '/tmp/audio/unknown', mime: 'audio/mpeg').isAudio, isTrue);
  });

  test('图片与视频不会被当成音频', () {
    expect(card(path: '/tmp/a.png', kind: 'png').isAudio, isFalse);
    expect(card(path: '/tmp/a.mp4', kind: 'mp4').isAudio, isFalse);
    expect(card(path: '/tmp/a.pptx', kind: 'pptx').isAudio, isFalse);
    expect(card(path: '/tmp/a.pdf', kind: 'pdf').isAudio, isFalse);
    expect(card(path: '/tmp/a.mp4', kind: 'mp4').isVideo, isTrue);
  });

  test('音频卡片不会走图片分支（渲染顺序回归）', () {
    final audio = card(path: '/tmp/final.mp3', kind: 'mp3', mime: 'audio/mpeg');
    expect(audio.isAudio, isTrue);
    expect(audio.isImage, isFalse);
  });
}
