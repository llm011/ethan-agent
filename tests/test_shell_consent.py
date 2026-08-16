"""shell 只读白名单 _is_safe_readonly 的安全回归测试。

该白名单决定哪些命令跳过 consent 弹窗直接执行，属于安全敏感逻辑：
- 正常只读探测命令应放行（免弹窗）
- 敏感文件读取（密钥/凭据）、环境变量 dump、任意文件内容读取必须弹窗
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ethan.tools.builtin.shell import _is_safe_readonly  # noqa: E402

# (命令, 期望放行)
CASES = [
    # ── 应放行：零副作用只读探测 ──
    ("ls ~/.ethan/skills/open-motion", True),
    ("ls -la /tmp", True),
    ("ls /tmp && echo done_marker", True),
    ("python3 -c \"from pathlib import Path; print(Path('/x').exists())\"", True),
    ("cat README.md", True),
    ("head -n 5 config.yaml", True),
    ("tail -20 server.log", True),
    ("stat app.py", True),
    ("wc -l main.py", True),
    ("pwd", True),
    ("which python3", True),
    ("whereis git", True),
    ("echo hello world", True),
    ("md5 dist/app.tar.gz", True),
    ("sha256sum file.bin", True),

    # ── 必须弹窗：敏感文件/目录读取（安全回归核心）──
    ("cat .env", False),
    ("cat .env.production", False),
    ("head -5 ~/.env.local", False),
    ("cat ~/.ssh/id_rsa", False),
    ("cat /root/.ssh/id_ed25519", False),
    ("head -3 ~/.aws/credentials", False),
    ("cat server.pem", False),
    ("cat ~/.netrc", False),
    ("cat ~/.git-credentials", False),
    ("cat ~/.config/gh/hosts.yml", False),    # gh CLI 明文 GitHub token
    ("cat ~/.bash_history", False),           # 历史命令常含 export 的密钥
    ("cat ~/.zsh_history", False),
    ("ls ~/.ssh", False),                     # 目录列表也保守拦截
    ("stat /etc/secret_config", False),       # 命名含 secret
    ("cat auth/tokens.json", False),          # 命名含 token
    ("wc -l password_policy.txt", False),     # 命名含 password（保守误伤可接受）

    # ── 必须弹窗：python -c 环境变量 dump / 任意文件读 ──
    ("python3 -c \"import os; print(dict(os.environ))\"", False),
    ("python3 -c \"import os; print(os.getenv('HOME'))\"", False),
    ("python3 -c \"print(open('/root/.ssh/id_rsa').read())\"", False),   # 只读 open 也拦
    ("python3 -c \"print(open('README.md').read())\"", False),           # 任意文件内容读取
    ("python3 -c \"from pathlib import Path; print(Path('.env').read_text())\"", False),
    ("python3 -c \"print(__import__('os').environ)\"", False),

    # ── 必须弹窗：python -c 黑名单绕过（严格白名单回归核心）──
    ("python3 -c \"from os import system; system('rm -rf /')\"", False),         # from-import 别名执行子进程
    ("python3 -c \"from pathlib import Path; Path('/x').write_text('pwned')\"", False),  # 方法直呼写文件
    ("python3 -c \"import os; os.remove('/x')\"", False),                       # os.remove 删文件
    ("python3 -c \"from shutil import rmtree; rmtree('/x')\"", False),          # 别名导入 rmtree
    ("python3 -c \"from pathlib import Path; print(Path('/x').exists()); import os; os.system('id')\"", False),  # 探测后拼接任意代码

    # ── 必须弹窗：组合符/写操作/危险命令 ──
    ("rm -rf /tmp/x", False),
    ("cat a > b", False),
    ("ls; rm x", False),
    ("cat f | sh", False),
    ("python3 -c \"open('a','w')\"", False),
    ("python3 -c \"import subprocess\"", False),
    ("curl http://x", False),
    ("mv a b", False),
]


def test_safe_readonly_matrix():
    fails = [
        (cmd, want, _is_safe_readonly(cmd))
        for cmd, want in CASES
        if _is_safe_readonly(cmd) != want
    ]
    assert not fails, f"白名单判定与预期不符: {fails}"


def test_secret_env_ref_blocks_even_normal_cmd(monkeypatch):
    """引用了已配置 secret 环境变量的命令必须弹窗（与 shell 注入同源口径）。"""
    monkeypatch.setattr(
        "ethan.tools.builtin.shell._detect_secret_env_refs",
        lambda cmd: ["OPENAI_API_KEY"] if "OPENAI_API_KEY" in cmd else [],
    )
    assert not _is_safe_readonly("echo $OPENAI_API_KEY")
    assert _is_safe_readonly("echo $PATH")  # 非 secret 变量不受影响
