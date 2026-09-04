import 'package:flutter/material.dart';

import 'models/app_models.dart';
import 'data/api_client.dart';
import 'data/config_store.dart';
import 'data/ethan_repository.dart';
import 'services/api_service.dart';
import 'screens/chat_screen.dart';
import 'screens/login_screen.dart';
import 'screens/more_screen.dart';
import 'screens/sessions_screen.dart';
import 'screens/workspace_screens.dart';
import 'theme.dart';

class EthanApp extends StatefulWidget {
  const EthanApp({super.key});
  @override
  State<EthanApp> createState() => _EthanAppState();
}

class _EthanAppState extends State<EthanApp> {
  ThemeMode themeMode = ThemeMode.system;
  ApiConfig? config;
  String? connectionNotice;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    Future.wait([ConfigStore().read(), ConfigStore().readTheme()])
        .then((values) {
      final saved = values[0] as ApiConfig?;
      final savedTheme = values[1] as ThemeMode;
      if (mounted) {
        setState(() {
          config = saved;
          themeMode = savedTheme;
          loading = false;
        });
      }
    });
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'Ethan Agent',
        theme: EthanTheme.light(),
        darkTheme: EthanTheme.dark(),
        themeMode: themeMode,
        home: loading
            ? const Scaffold(body: Center(child: CircularProgressIndicator()))
            : config == null
                ? LoginScreen(onLogin: _login)
                : MainShell(
                    key: ValueKey('${config!.baseUrl}|${config!.token}'),
                    config: config!,
                    connectionNotice: connectionNotice,
                    themeMode: themeMode,
                    onTheme: (mode) async {
                      await ConfigStore().saveTheme(mode);
                      if (mounted) setState(() => themeMode = mode);
                    },
                    onConfig: _replaceConfig,
                    onLogout: () async {
                      await ConfigStore().clear();
                      if (mounted) {
                        setState(() {
                          config = null;
                          connectionNotice = null;
                        });
                      }
                    },
                  ),
      );

  Future<void> _login(String server, String token) async {
    final next = ApiConfig(
      baseUrl: server.isEmpty ? 'http://127.0.0.1:8900' : server,
      token: token,
    );
    // `mock-token` preserves the local-development login interaction. It only
    // skips authentication; every page still loads its business data from the
    // configured Ethan backend.
    if (token == 'mock-token') {
      await ConfigStore().save(next);
      if (mounted) {
        setState(() {
          config = next;
          connectionNotice = null;
        });
      }
      return;
    }

    final api = EthanApiClient(next);
    String? notice;
    try {
      await api.health();
      await api.authenticate();
    } catch (error) {
      // Connection is advisory at login: let the user inspect the app and
      // retry from Settings instead of trapping them on the login screen.
      notice = '服务未连接：$error';
    } finally {
      api.close();
    }
    await ConfigStore().save(next);
    if (mounted) {
      setState(() {
        config = next;
        connectionNotice = notice;
      });
    }
  }

  Future<void> _replaceConfig(ApiConfig next) async {
    await ConfigStore().save(next);
    if (mounted) setState(() => config = next);
  }
}

class MainShell extends StatefulWidget {
  const MainShell({
    required this.config,
    required this.themeMode,
    required this.onTheme,
    required this.onConfig,
    required this.onLogout,
    this.connectionNotice,
    super.key,
  });
  final ApiConfig config;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onTheme;
  final Future<void> Function(ApiConfig config) onConfig;
  final VoidCallback onLogout;
  final String? connectionNotice;
  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  // The conversation is the primary action and intentionally sits in the
  // centre of the three-item navigation, like a tab bar with a clear home.
  var selected = 1;
  String? sessionId;
  late final EthanApiClient api;
  late final EthanApiService service;
  late final EthanRepository repository;

  @override
  void initState() {
    super.initState();
    api = EthanApiClient(widget.config);
    service = EthanApiService(widget.config);
    repository = EthanRepository(service);
    if (widget.connectionNotice != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        showDialog<void>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            icon: const Icon(Icons.cloud_off_outlined),
            title: const Text('服务未连接'),
            content: Text(widget.connectionNotice!),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('稍后处理'),
              ),
              FilledButton(
                onPressed: () {
                  Navigator.pop(dialogContext);
                  select(2);
                },
                child: const Text('打开设置'),
              ),
            ],
          ),
        );
      });
    }
  }

  @override
  void dispose() {
    api.close();
    super.dispose();
  }

  void select(int index) => setState(() => selected = index);

  void _showChat(String? id) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      setState(() {
        sessionId = id;
        selected = 1;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      WorkspaceScreen(
        api: api,
        workspaceApi: service,
        onOpenSession: (id) {
          _showChat(id);
        },
        onOpenAll: () => _openAllSessions(context),
        onOpenTasks: () => _openMore(context, 'background'),
        onNewChat: () {
          _showChat(null);
        },
        onOpenMine: () => select(2),
      ),
      ChatScreen(
          api: api,
          workspaceApi: service,
          sessionId: sessionId,
          onMenu: () => _showSessionDrawer(context)),
      MoreScreen(
        onOpen: (route) => _openMore(context, route),
        onOpenSettings: () => _openSettings(context),
      ),
      // Kept as a local builder target so the Settings page remains a
      // full-screen, Apple-style pushed page rather than a fourth tab.
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final expanded = constraints.maxWidth >= 600;
        final body = IndexedStack(index: selected, children: pages);
        if (!expanded) {
          return Scaffold(
            body: body,
            bottomNavigationBar: NavigationBar(
              selectedIndex: selected,
              onDestinationSelected: select,
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.grid_view_rounded),
                  selectedIcon: Icon(Icons.grid_view_rounded),
                  label: '工作台',
                ),
                NavigationDestination(
                  icon: Icon(Icons.chat_bubble_outline_rounded),
                  selectedIcon: Icon(Icons.chat_bubble_rounded),
                  label: '对话',
                ),
                NavigationDestination(
                  icon: Icon(Icons.person_outline_rounded),
                  selectedIcon: Icon(Icons.person_rounded),
                  label: '我的',
                ),
              ],
            ),
          );
        }
        return Scaffold(
          body: Row(
            children: [
              NavigationRail(
                selectedIndex: selected,
                onDestinationSelected: select,
                labelType: NavigationRailLabelType.all,
                leading: Padding(
                  padding: const EdgeInsets.only(bottom: 26),
                  child: Icon(
                    Icons.auto_awesome_rounded,
                    color: Theme.of(context).colorScheme.primary,
                    size: 30,
                  ),
                ),
                destinations: const [
                  NavigationRailDestination(
                    icon: Icon(Icons.grid_view_rounded),
                    selectedIcon: Icon(Icons.grid_view_rounded),
                    label: Text('工作台'),
                  ),
                  NavigationRailDestination(
                    icon: Icon(Icons.chat_bubble_outline_rounded),
                    selectedIcon: Icon(Icons.chat_bubble_rounded),
                    label: Text('对话'),
                  ),
                  NavigationRailDestination(
                    icon: Icon(Icons.person_outline_rounded),
                    selectedIcon: Icon(Icons.person_rounded),
                    label: Text('我的'),
                  ),
                ],
              ),
              const VerticalDivider(width: 1),
              Expanded(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 900),
                    child: body,
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  void _showSessionDrawer(BuildContext context) => showModalBottomSheet(
        context: context,
        showDragHandle: true,
        builder: (_) => SafeArea(
          child: SizedBox(
            height: 430,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 4),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('最近对话',
                          style: Theme.of(context).textTheme.titleLarge),
                      FilledButton.icon(
                        onPressed: () {
                          Navigator.pop(context);
                          _showChat(null);
                        },
                        icon: const Icon(Icons.add_rounded),
                        label: const Text('新对话'),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: FutureBuilder<List<Session>>(
                    future: api.sessions(),
                    builder: (context, snapshot) {
                      if (snapshot.connectionState != ConnectionState.done)
                        return const Center(child: CircularProgressIndicator());
                      if (snapshot.hasError)
                        return Center(child: Text('加载失败：${snapshot.error}'));
                      final sessions = snapshot.data ?? const <Session>[];
                      if (sessions.isEmpty)
                        return const Center(child: Text('暂无会话'));
                      return ListView(
                          children: sessions
                              .take(3)
                              .map((s) => ListTile(
                                    leading: const Icon(
                                        Icons.chat_bubble_outline_rounded),
                                    title: Text(s.title),
                                    subtitle: Text(s.time),
                                    onTap: () {
                                      Navigator.pop(context);
                                      _showChat(s.id);
                                    },
                                  ))
                              .toList());
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      );

  void _openMore(BuildContext context, String route) {
    final page = switch (route) {
      'memory' => MemoryScreen(api: service, repository: repository),
      'knowledge' => ResourceScreen(kind: 'knowledge', api: service),
      'skills' => ResourceScreen(kind: 'skills', api: service),
      'docs' => ResourceScreen(kind: 'docs', api: service),
      'logs' => ResourceScreen(kind: 'logs', api: service),
      'agenda' => AgendaScreen(api: service, repository: repository),
      'schedule' => ScheduleScreen(
          api: service,
          repository: repository,
          onOpenSession: (id) {
            Navigator.of(context).pop();
            _showChat(id);
          }),
      'background' => BackgroundTasksScreen(
          api: service,
          onOpenSession: (id) {
            Navigator.of(context).pop();
            _showChat(id);
          }),
      _ => ResourceScreen(kind: 'memory', api: service),
    };
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => page));
  }

  void _openSettings(BuildContext context) {
    Navigator.of(context)
        .push<ApiConfig>(MaterialPageRoute(
      builder: (_) => SettingsScreen(
        server: widget.config.baseUrl,
        token: widget.config.token,
        api: service,
        themeMode: widget.themeMode,
        onTheme: widget.onTheme,
      ),
    ))
        .then((next) {
      if (next != null && mounted) widget.onConfig(next);
    });
  }

  void _openAllSessions(BuildContext context) {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => SessionsScreen(
        api: api,
        onOpen: (id) {
          Navigator.of(context).pop();
          _showChat(id);
        },
      ),
    ));
  }
}
