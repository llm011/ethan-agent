class ApiConfig {
  const ApiConfig({required this.baseUrl, required this.token});

  final String baseUrl;
  final String token;

  /// Same origin normalization as Android's `ServerUrlUtils`: pasted `/api`
  /// or page paths are removed before API routes are composed.
  String get origin {
    var value = baseUrl.trim();
    // A common paste error is appending a new address to the default one,
    // e.g. `http://127.0.0.1:8900https://server.example`. Android recovers by
    // using the last explicit scheme; keep both clients on the same server.
    final lastHttp = value.lastIndexOf('http://');
    final lastHttps = value.lastIndexOf('https://');
    final schemeIndex = lastHttp > lastHttps ? lastHttp : lastHttps;
    if (schemeIndex > 0) value = value.substring(schemeIndex);
    if (!value.contains('://')) value = 'https://$value';
    final uri = Uri.tryParse(value);
    if (uri == null ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty) {
      throw FormatException('无效的服务器地址：$baseUrl');
    }
    final host = uri.host.contains(':') ? '[${uri.host}]' : uri.host;
    final port = uri.hasPort ? ':${uri.port}' : '';
    return '${uri.scheme}://$host$port';
  }

  String get apiBase => '$origin/api';
}

class ChatMessage {
  const ChatMessage({
    required this.text,
    required this.isUser,
    required this.time,
    this.id,
    this.toolSteps = const [],
    this.isStreaming = false,
    this.quote,
    this.images = const [],
    this.cards = const [],
    this.usage,
    this.ttfbMs,
    this.totalDurationMs,
    this.generationDurationMs,
  });

  final String text;
  final bool isUser;
  final String time;
  final String? id;
  final List<ToolStep> toolSteps;
  final bool isStreaming;
  final QuoteInfo? quote;
  final List<MessageImage> images;
  final List<MediaCard> cards;
  final UsageInfo? usage;
  final int? ttfbMs;
  final int? totalDurationMs;
  final int? generationDurationMs;

  /// Compact label retained by the Android UI for tool progress chips.
  String? get tool => toolSteps.isEmpty ? null : '${toolSteps.length} 个工具步骤';
}

/// Structured cards persisted by Ethan messages. File cards are authorized
/// by the session and must be opened through the files API; image cards may
/// contain either a data URL or a remote URL.
class MediaCard {
  const MediaCard({
    required this.type,
    this.path = '',
    this.title = '',
    this.mime = '',
    this.kind = '',
    this.projectDir,
    this.url = '',
    this.localPath = '',
  });

  final String type;
  final String path;
  final String title;
  final String mime;
  final String kind;
  final String? projectDir;
  final String url;
  final String localPath;

  bool get isFile => type == 'file' && path.isNotEmpty;
  bool get isImage =>
      type == 'image' ||
      _extension == 'png' ||
      _extension == 'jpg' ||
      _extension == 'jpeg' ||
      _extension == 'gif' ||
      _extension == 'webp' ||
      _extension == 'svg' ||
      _extension == 'bmp' ||
      mime.startsWith('image/');
  bool get isVideo => _extension == 'mp4' || mime.startsWith('video/');
  bool get isPpt => _extension == 'pptx' || kind.toLowerCase() == 'pptx';

  String get _extension {
    final value = path.isNotEmpty ? path : localPath;
    final dot = value.lastIndexOf('.');
    return dot < 0 ? '' : value.substring(dot + 1).toLowerCase();
  }
}

class QuoteInfo {
  const QuoteInfo({required this.role, required this.content});
  final String role;
  final String content;
}

class UsageInfo {
  const UsageInfo({this.input = 0, this.output = 0, this.cache = 0});
  final int input;
  final int output;
  final int cache;
}

class SubToolStep {
  const SubToolStep(
      {required this.tool,
      this.args = '',
      this.state = 'start',
      this.durationMs,
      this.resultPreview});
  final String tool;
  final String args;
  final String state;
  final int? durationMs;
  final String? resultPreview;
  SubToolStep copyWith(
          {String? tool,
          String? args,
          String? state,
          int? durationMs,
          String? resultPreview}) =>
      SubToolStep(
          tool: tool ?? this.tool,
          args: args ?? this.args,
          state: state ?? this.state,
          durationMs: durationMs ?? this.durationMs,
          resultPreview: resultPreview ?? this.resultPreview);
}

class MessageImage {
  const MessageImage({this.data, this.mediaType, this.url, this.displayUrl});
  final String? data;
  final String? mediaType;
  final String? url;
  final String? displayUrl;
}

class ToolStep {
  const ToolStep({
    required this.tool,
    this.id,
    this.args = '',
    this.state = 'start',
    this.durationMs,
    this.resultPreview,
    this.resultDetail,
    this.thought,
    this.intent,
    this.subSteps = const [],
  });

  final String tool;
  final String? id;
  final String args;
  final String state;
  final int? durationMs;
  final String? resultPreview;
  final String? resultDetail;
  final String? thought;
  final String? intent;
  final List<SubToolStep> subSteps;

  ToolStep copyWith({
    String? tool,
    String? id,
    String? args,
    String? state,
    int? durationMs,
    String? resultPreview,
    String? resultDetail,
    String? thought,
    String? intent,
    List<SubToolStep>? subSteps,
  }) =>
      ToolStep(
        tool: tool ?? this.tool,
        id: id ?? this.id,
        args: args ?? this.args,
        state: state ?? this.state,
        durationMs: durationMs ?? this.durationMs,
        resultPreview: resultPreview ?? this.resultPreview,
        resultDetail: resultDetail ?? this.resultDetail,
        thought: thought ?? this.thought,
        intent: intent ?? this.intent,
        subSteps: subSteps ?? this.subSteps,
      );
}

class OnboardingStatus {
  const OnboardingStatus({this.firstTime = false, this.message = ''});
  final bool firstTime;
  final String message;
}

class ModelEntry {
  const ModelEntry({
    required this.id,
    required this.provider,
    this.description = '',
    this.aliases = const [],
  });
  final String id;
  final String provider;
  final String description;
  final List<String> aliases;
}

class ModeEntry {
  const ModeEntry({
    required this.key,
    required this.label,
    this.icon = '',
    this.accent = '',
    this.blurb = '',
  });
  final String key;
  final String label;
  final String icon;
  final String accent;
  final String blurb;
}

class ConsentInfo {
  const ConsentInfo({
    required this.requestId,
    required this.tool,
    required this.description,
    this.detail,
  });
  final String requestId;
  final String tool;
  final String description;
  final String? detail;
}

class AskUserInfo {
  const AskUserInfo({
    required this.requestId,
    required this.question,
    required this.options,
    required this.defaultValue,
    required this.timeout,
  });
  final String requestId;
  final String question;
  final List<AskUserOption> options;
  final String defaultValue;
  final int timeout;
}

class AskUserOption {
  const AskUserOption({required this.label, required this.value});
  final String label;
  final String value;
}

class WaitForUserInfo {
  const WaitForUserInfo({
    required this.requestId,
    required this.prompt,
    required this.inputType,
    required this.placeholder,
    required this.confirmLabel,
    required this.cancelLabel,
    required this.timeout,
  });
  final String requestId;
  final String prompt;
  final String inputType;
  final String placeholder;
  final String confirmLabel;
  final String cancelLabel;
  final int timeout;
}

class Session {
  const Session({
    required this.id,
    required this.title,
    required this.summary,
    required this.time,
    this.model = '',
    this.source = 'web',
    this.mode,
    this.pinnedAt = 0,
  });

  final String id;
  final String title;
  final String summary;
  final String time;
  final String model;
  final String source;
  final String? mode;
  final int pinnedAt;
}

class SessionDetail {
  const SessionDetail({
    required this.id,
    required this.title,
    required this.model,
    required this.messages,
    this.mode,
  });

  final String id;
  final String title;
  final String model;
  final String? mode;
  final List<ChatMessage> messages;
}

class AnnotationItem {
  const AnnotationItem({
    required this.id,
    required this.messageId,
    required this.type,
    required this.start,
    required this.end,
    this.color,
    this.quote,
    this.note,
  });
  final int id;
  final int messageId;
  final String type;
  final int start;
  final int end;
  final String? color;
  final String? quote;
  final String? note;
}

class DeckSlide {
  const DeckSlide({
    required this.index,
    required this.title,
    required this.content,
  });
  final int index;
  final String title;
  final String content;
}
