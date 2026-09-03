import 'package:flutter/material.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({required this.onLogin, super.key});
  final Future<void> Function(String server, String token) onLogin;
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final server = TextEditingController(text: 'http://127.0.0.1:8900');
  final token = TextEditingController(text: 'mock-token');
  bool obscure = true;
  bool busy = false;
  String? error;

  @override
  void dispose() {
    server.dispose();
    token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(28),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 430),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Container(
                      padding: const EdgeInsets.all(22),
                      decoration: BoxDecoration(
                        color: Theme.of(context).colorScheme.primaryContainer,
                        shape: BoxShape.circle,
                      ),
                      child: Icon(
                        Icons.auto_awesome_rounded,
                        size: 48,
                        color: Theme.of(context).colorScheme.primary,
                      ),
                    ),
                    const SizedBox(height: 22),
                    Text(
                      'Ethan Agent',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.displaySmall?.copyWith(
                            fontWeight: FontWeight.w800,
                          ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '连接你的私人 AI 助手',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                    const SizedBox(height: 36),
                    TextField(
                      controller: server,
                      decoration: const InputDecoration(
                        labelText: '服务器地址',
                        prefixIcon: Icon(Icons.dns_rounded),
                        hintText: 'http://192.168.1.100:8900',
                      ),
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: token,
                      obscureText: obscure,
                      decoration: InputDecoration(
                        labelText: 'Access Token',
                        prefixIcon: const Icon(Icons.key_rounded),
                        suffixIcon: IconButton(
                          onPressed: () => setState(() => obscure = !obscure),
                          icon: Icon(
                            obscure
                                ? Icons.visibility_rounded
                                : Icons.visibility_off_rounded,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Text(error!,
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error)),
                      ),
                    FilledButton.icon(
                      onPressed: busy
                          ? null
                          : () async {
                              setState(() {
                                busy = true;
                                error = null;
                              });
                              try {
                                await widget.onLogin(
                                    server.text.trim(), token.text.trim());
                              } catch (e) {
                                if (mounted)
                                  setState(() => error = e.toString());
                              } finally {
                                if (mounted) setState(() => busy = false);
                              }
                            },
                      icon: const Icon(Icons.login_rounded),
                      label: const Padding(
                        padding: EdgeInsets.all(12),
                        child: Text('登录 Ethan'),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Token 仅保存在本机。登录后可在设置中修改连接。',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
}
