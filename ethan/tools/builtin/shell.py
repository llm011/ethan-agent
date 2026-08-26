import asyncio
import os
import re
import shutil
import signal

from ethan.tools.base import BaseTool

# 依赖外部 CLI 的命令 → 缺失时的友好安装引导。命中后不执行命令，直接返回引导文案，
# 避免首次使用者只拿到一句晦涩的 "command not found"。key 用词边界匹配命令串。
_MISSING_BIN_HINTS = {
    "lark-cli": (
        "飞书功能依赖 lark-cli，但当前环境未安装。\n"
        "安装（macOS）：`brew install larksuite/tap/lark-cli`\n"
        "安装后首次使用需登录授权：`lark-cli auth login`\n"
        "（其他平台请参考 lark-cli 文档自行安装。）"
    ),
}

# 高危命令分两级（2026-08-22 调整，用户反馈超级模式下 curl 等日常命令被反复弹窗）：
#
# · 破坏性（_DESTRUCTIVE_PATTERNS）：不可逆的本地数据/系统破坏。即使超级权限
#   （auto_consent）模式也强制弹窗交还用户拍板——见 ShellTool.consent_destructive。
# · 高危非破坏性（_RISKY_PATTERNS）：提权 / 下载管道执行 / 动态执行 / 危险权限。
#   普通模式下与破坏性同等对待（每次必问、不计会话放行）；超级权限模式下
#   自动放行——用户开启超级权限即接管这部分风险，避免日常命令被反复打断。
#
# 两级合计仍构成完整高危集合 _DANGEROUS_RE：普通模式行为不变。
_DESTRUCTIVE_PATTERNS = [
    # rm -rf / -r -f / -fr / -R（大写递归）及 GNU 长参数 --recursive / --force，
    # 支持短长混合（rm -r --force、rm --interactive=always --force 等）。
    r'\brm\s+(?:-[^\s]+\s+)*-(?:\w*[rfR]|-(?:recursive|force))\b',
    r'\bmkfs\b|\bfdisk\b|\bparted\b',          # 格式化/分区
    r'\bdd\b\s+.*\bof=',                       # dd 写盘
    # 覆写系统/设备文件。/dev/null、/dev/stdout、/dev/stderr 是重定向黑洞/透传目标，
    # 写入无副作用，放行（否则 `2>/dev/null` 这类极常见写法会被误判高危，
    # 在超级权限模式下被静默拒绝）；/dev/sda、/dev/tcp 等仍拦截。
    r'>\s*/dev/(?!null\b|stdout\b|stderr\b)|>\s*/etc/|>\s*/sys/|>\s*/boot/',
    r':\(\)\s*\{.*\|.*&.*\}',                   # fork bomb
    r'\bgit\b.*\b(?:reset\s+--hard|clean\s+-\w*[fd]|push\s+.*--force|push\s+.*-f)\b',  # 破坏性 git
]
_RISKY_PATTERNS = [
    r'\b(?:sudo|doas)\b',                       # 提权
    r'\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b',  # 下载管道执行
    r'\beval\b|\bsource\s+/dev/stdin',          # eval / 执行 stdin
    r'\bchmod\s+(?:-\w+\s+)*0?777\b|\bchown\s+-\w*R',  # 危险权限/递归改属主
]
_DESTRUCTIVE_RE = re.compile("|".join(_DESTRUCTIVE_PATTERNS))
_DANGEROUS_RE = re.compile("|".join(_DESTRUCTIVE_PATTERNS + _RISKY_PATTERNS))

# 检测命令里引用 secret 环境变量的语法：$VAR / ${VAR}。
# secrets 通过 load_secret_env() 注入 shell 子进程环境（见 run()），agent 可被诱导
# `echo $TOKEN | base64` 套出密钥（编码后可绕过 mask_text 的全字符串匹配）。
# 命中时走高危路径——每次重新授权、不计入会话放行，让用户在授权弹窗里看到具体
# 引用了哪个 secret 变量，再决定是否放行。
_DOLLAR_VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}|\$([A-Za-z_][A-Za-z0-9_]*)')

# 能列举环境变量的命令：env/printenv/set/export -p/declare -x/compgen -v。
# 这些命令不需要 $VAR 语法就能 dump 所有 secret（含注入的密钥），必须单独拦截。
# 判定要求命令出现在「命令位置」（命令串开头，或 ; | & ( ` 换行等 shell 分隔符
# 之后，剥掉 VAR= 赋值前缀），而不是字符串任意位置——旧版按 \b 词边界 + 后瞻
# 分隔符匹配，URL 里的 env/set 子串会被误判：
#   curl -sL https://api.x.com/v1/env | jq     （路径以 /env 结尾 + 管道）
#   curl -sL 'https://x.com/a?token=env&u=1'   （查询串里的 env& ）
#   curl -sL https://x.com/set                 （路径以 /set 结尾）
# 这些误判走 always 路径，导致超级权限模式下 curl 也被强制弹窗（2026-08-22 反馈）。
_ENV_DUMP_SPLIT_RE = re.compile(r'[;\n|&`]')  # 切分命令段（含 || && 的组成部分）
_ENV_DUMP_HEAD_RE = re.compile(
    r'^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*'  # 剥掉 VAR=val 赋值前缀
    r'(?:[^\s/=]*/)*'                        # 可选路径前缀：/usr/bin/env、./env、bin/printenv
    r'(printenv|env|set|export|declare|compgen)\b\s*(.*)$',
    re.DOTALL,
)


def _is_env_dump(command: str) -> bool:
    """命令是否会在某段中以 env/printenv/set 等列举环境变量（含注入的 secret）。"""
    for seg in _ENV_DUMP_SPLIT_RE.split(command or ""):
        m = _ENV_DUMP_HEAD_RE.match(seg.strip())
        if not m:
            continue
        head, rest = m.group(1), (m.group(2) or "").strip()
        if head == "printenv":
            return True
        if head in ("env", "set"):
            # 裸 env/set 才是 dump；带参数（env VAR=1 cmd / set -x）是设置/执行
            if not rest:
                return True
        elif head == "export" and rest.startswith("-p"):
            return True
        elif head == "declare" and re.match(r'-\w*[xp]', rest):
            return True
        elif head == "compgen" and rest.startswith("-v"):
            return True
    return False

# 只读无副作用命令白名单：匹配到直接跳过 consent 弹窗。
# 目的：避免「ls 某脚本目录是否存在 / python -c 仅 Path.exists() 探测」
# 这类零风险命令被误拒后，模型绕到 web_fetch 等低质量替代路径。
# 注意：这只是不弹授权，不影响其他安全拦截（_DANGEROUS_RE / _is_env_dump 仍优先命中）。
_SAFE_READONLY_CMD_RE = re.compile(
    r'^(?:'
    # ls 纯列表：允许 ls + 路径/通配 + 常见只读选项 + 尾部 && echo <标识符>
    r'ls\s+(?:-[ahlLdsinrtSuUgGmkpZ1@\,]+\s+)?(?:(?:--?(?:time|sort|color|width|tabsize|block-size|ignore|indicator-style|context|classify|hide|group-directories-first)\S*\s+)?)*[\w~/.\-*?[\]{}]+\s*(?:&&\s*echo\s+[A-Za-z_][A-Za-z0-9_]*)?'
    # python/python3 -c 单行脚本（安全性由 _PY_C_STRICT_RE 严格结构白名单兜底：
    # 仅放行 Path(...).exists() 探测形态，其余一律照常弹窗）
    r'|python3?\s+-c\s+"[^"]*"'
    r'|python3?\s+-c\s+\'[^\']*\''
    # 纯文本只读：cat/head/tail/file/stat/wc 加一个普通路径/可选参数（head -n 5 等）
    r'|(?:cat|head|tail|file|stat|wc)\s+(?:-[A-Za-z0-9]+\s+)?(?:[A-Za-z0-9_\-]+\s+)?[\w~/.\-\[\]{}]+'
    # pwd / which / whereis
    r'|pwd'
    r'|which\s+[\w\-]+'
    r'|whereis\s+[\w\-]+'
    # echo 简单字符串（不含 $VAR 引用 secret 的，由 helper 扫）
    r'|echo\s+[\w\s~/.\-:,_=+#@!?$%^&\[\]{}()<>\/]+'
    # md5/sha 校验文件
    r'|(?:md5|sha1|sha256|sha512|md5sum|sha256sum|sha512sum)\s+[\w~/.\-]+'
    r')\s*$'
)
# 命令级危险组合符：非 Python `-c`/`-c` 字符串字面量上下文里命中任一，说明命令不是纯读。
# 注意：末尾 `&& echo <标识符>` 这类常见"探测成功打标记"用法会单独放行（见 `_is_safe_readonly`）。
_DANGEROUS_COMPOSE_RE = re.compile(
    r'>>?'                          # 重定向 > / >>
    r'|\|'                          # 管道 |（包含 ||）
    r'|;\s*'                        # 命令分隔
    r'|&\s+'                        # 后台执行 &（区分 &&/& 后面不是&）
    r'|`'                           # 反引号子 shell
    r'|\$\('                        # $(...) 子 shell
    r'|&&'                          # && 组合（含例外，见下）
    r'|\|\|'                        # || 组合
    r'|\beval\b|\bsource\b|\bexec\b'  # 动态执行/加载
)

# 从命令里剥离 `python -c "...script..."` / `python -c '...script...'`
# 的脚本字符串内容，让后续危险组合符只查「shell 层」而不是 Python 源码层。
# 否则 Python 源码里的 `.write(` / `||` / `&&` 会把纯探测 Python 误判成危险。
_STRIP_PY_C_STR_RE = re.compile(
    r'''(\bpython3?\s+-c\s+)("[^"\n]*(?:\\.[^"\n]*)*"|'[^'\n]*(?:\\.[^'\n]*)*')'''
)

# python -c 脚本的严格结构白名单：唯一放行形态是
#   from pathlib import Path; print(Path('<路径字面量>').exists())
# 此前按危险特性黑名单扫描（禁 open/write/import os…），可被 `from os import
# system`、`from shutil import rmtree`、`Path(...).write_text(...)` 等别名导入/
# 方法直呼完全绕过，导致任意子进程/写文件被判定只读免弹窗。改为结构性白名单：
# 不匹配此形态的 python -c 一律照常走 consent。路径字面量内禁止引号/换行，
# 杜绝闭合引号后拼接任意代码。
_PY_C_STRICT_RE = re.compile(
    r"""^from pathlib import Path; print\(Path\((['"])[^'"\n]*\1\)\.exists\(\)\)\s*$"""
)

# 敏感文件/目录模式：cat/head/ls 等只读命令的「读取路径」命中即不免单。
# 密钥/凭据文件的读取此前靠 consent 弹窗作为唯一人工闸门，白名单不得绕过。
# 保守取向：宁可误伤（如 ls ~/.ssh 目录列表也弹窗），不可漏放。
_SENSITIVE_PATH_RE = re.compile(
    r'(?:'
    r'\.ssh\b|id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys'          # SSH 私钥/凭据
    r'|\.aws\b|credentials'                                               # AWS / 通用凭据
    r'|\.env[\w.]*'                                                       # .env / .env.local / .env.production
    r'|\.pem\b|\.key\b|\.p12\b|\.pfx\b'                                   # 证书/私钥文件
    r'|\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.docker/config'        # 带token的配置
    r'|\.gnupg\b'                                                         # GPG
    r'|secrets?[\w./-]*|token[\w./-]*|password[\w./-]*'                  # 命名含 secret/token/password 的路径
    r'|\.config/gh[\w./-]*|gh/hosts\b'                                    # gh CLI 凭据（hosts.yml 含明文 GitHub token）
    r'|[\w./-]*history\b'                                                 # shell 历史（.bash_history/.zsh_history 常含 export 的密钥）
    r')',
    re.IGNORECASE,
)


def _shell_level_command(cmd: str) -> str:
    """把 python3 -c "...内联脚本..." 的脚本字符串替换成占位，仅保留 shell 层面的 token。

    这样判断 `>/>>/|/;&/&&/||` 等组合符时，不会被 Python 源码里的 `x if a else b`
    （Python 内部不含 ||/&& 但单引号字符、.write( 等会触发其他拦截）等误伤。
    """
    return _STRIP_PY_C_STR_RE.sub(r'\1"PYC"', cmd)


def _is_allowed_echo_tail(cmd: str) -> bool:
    """匹配 `... && echo <标识符>` 这种末尾纯只读组合，返回 True。"""
    return bool(re.search(r'&&\s*echo\s+[A-Za-z_][A-Za-z0-9_]*\s*$', cmd))


def _is_rm_tmp_only(command: str) -> bool:
    """rm 命令的所有操作目标是否全部位于 /tmp/ 下。

    只检查 rm 开头的命令；如果命令有管道/分号组合，保守返回 False。
    """
    cmd = (command or "").strip()
    if not re.match(r'\brm\b', cmd):
        return False
    if re.search(r'[;|&`]|\$\(', cmd):
        return False
    parts = cmd.split()
    paths = [p for p in parts[1:] if not p.startswith("-")]
    if not paths:
        return False
    return all(p.startswith("/tmp/") or (p == "/tmp") for p in paths)


def _is_safe_readonly(command: str) -> bool:
    """保守判定 cmd 是否纯读、零副作用。命中可免 consent 弹窗。"""
    cmd = (command or "").strip()
    if not cmd:
        return False
    # 0. 引用 secret 环境变量的（即使只读也可能泄露密钥）不免单
    if _detect_secret_env_refs(cmd):
        return False
    # 0.5 读取路径命中敏感文件模式（.env / id_rsa / credentials 等）不免单：
    #     密钥文件的读取此前靠 consent 作为唯一人工闸门，白名单不得绕过
    if _SENSITIVE_PATH_RE.search(cmd):
        return False
    # 1. 基础白名单正则过（格式正确 + 只读命令种类）
    if not _SAFE_READONLY_CMD_RE.match(cmd):
        return False
    # 2. 危险组合符拦截：仅在「剥离 python -c 内联脚本」的 shell 层检查，
    #    避免 Python 源码字符（括号、引号）误伤。
    shell_only = _shell_level_command(cmd)
    if _DANGEROUS_COMPOSE_RE.search(shell_only):
        if not _is_allowed_echo_tail(cmd):
            return False
        # 对允许的 && echo <标识符>，再确认除了这个「一次 && echo」之外没有其他组合符
        rest = re.sub(r'&&\s*echo\s+[A-Za-z_][A-Za-z0-9_]*\s*$', '', shell_only).strip()
        if _DANGEROUS_COMPOSE_RE.search(rest):
            return False
    # 3. python -c 的额外过滤：严格结构白名单，仅放行
    #    `from pathlib import Path; print(Path('...').exists())` 路径探测形态。
    #    此前的危险特性黑名单可被 from-import 别名（from os import system、
    #    from shutil import rmtree）或方法直呼（Path(...).write_text）绕过，
    #    故不匹配 _PY_C_STRICT_RE 的一律弹窗。
    m = _STRIP_PY_C_STR_RE.search(cmd)
    if m:
        script_body = m.group(2)
        if script_body:
            # 去掉首尾一层引号
            script_body = script_body[1:-1]
        if not _PY_C_STRICT_RE.match(script_body or ""):
            return False
    return True


def _extract_dollar_vars(command: str) -> set[str]:
    """提取命令里所有 $VAR / ${VAR} 引用的变量名。"""
    refs: set[str] = set()
    for m in _DOLLAR_VAR_RE.finditer(command):
        name = m.group(1) or m.group(2)
        if name:
            refs.add(name)
    return refs


def _detect_secret_env_refs(command: str) -> list[str]:
    """命令引用了哪些已注入的 secret 环境变量，返回命中的变量名（排序）。

    与 shell 子进程注入同源（load_secret_env），确保检测口径和注入口径一致。
    """
    try:
        from ethan.core.secrets_store import load_secret_env
        secret_keys = set(load_secret_env().keys())
    except Exception:
        return []
    if not secret_keys:
        return []
    return sorted(_extract_dollar_vars(command) & secret_keys)


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Kill 整个进程组（含孙进程），兼容进程已退出的情况。

    start_new_session=True 时子进程是进程组 leader，os.killpg 能传播 SIGKILL 给所有子进程。
    进程已退出则 getpgid 抛 ProcessLookupError，静默忽略。
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    except Exception:
        pass
    try:
        proc.wait()
    except Exception:
        pass


class ShellTool(BaseTool):
    cacheable = False  # shell 命令有副作用，结果不可缓存
    side_effect = True
    no_compress = True  # 脚本输出（如 query_devices 设备列表）需逐字给模型，压成摘要会丢 entity_id
    name = "shell"
    description = "Execute a shell command and return its output."

    def consent_check(self, command: str = "", **kwargs) -> str | None:
        # shell 可执行任意副作用操作，执行前请求授权。
        cmd = command or ""
        if _DANGEROUS_RE.search(cmd):
            # 高危命令：文案标红提示，且每次都问（见 consent_always）
            return f"⚠️ 高危 shell 命令，请确认：{cmd[:200]}"
        # 环境变量列举命令（env/printenv/set 等）：不需要 $VAR 就能 dump 所有 secret，
        # 每次重新授权。
        if _is_env_dump(cmd):
            return f"⚠️ 命令可能泄露环境变量（含 secret），请确认：{cmd[:200]}"
        # 命令引用了 secret 环境变量：可被诱导泄露密钥（编码能绕过 mask_text），
        # 每次重新授权，让用户在弹窗里看到具体引用了哪个 secret 变量。
        secret_refs = _detect_secret_env_refs(cmd)
        if secret_refs:
            return (
                f"⚠️ 命令引用了 secret 环境变量（{', '.join(secret_refs)}），"
                f"可能泄露密钥，请确认：{cmd[:200]}"
            )
        # 纯读/零副作用命令（ls 目录探测、python -c 仅 Path.exists 等）：
        # 直接放行，不弹 consent 弹窗，避免新会话首次就被拒，
        # 导致模型绕到 web_fetch 等低质量替代路径。
        if _is_safe_readonly(cmd):
            return None
        # 普通命令：文案显式告知 scope 是会话级，避免用户以为只授了卡片上那一条
        return "执行 shell 命令（授权后本会话内的所有 shell 命令都不再询问）"

    def consent_always(self, command: str = "", **kwargs) -> bool:
        # 高危命令始终重新询问，即使本会话已授权过 shell，也不计入会话放行。
        # 这是普通模式/无人值守模式的口径（破坏性 + 高危非破坏性 + 密钥泄露面）。
        # 例外：rm 操作目标全部在 /tmp/ 下时放行，不反复弹窗。
        cmd = command or ""
        if _DANGEROUS_RE.search(cmd):
            if _is_rm_tmp_only(cmd):
                return False
            return True
        return _is_env_dump(cmd) or bool(_detect_secret_env_refs(cmd))

    def consent_destructive(self, command: str = "", **kwargs) -> bool:
        # 破坏性命令（rm -rf / 格式化 / 写设备 / fork 炸弹 / 破坏性 git）：
        # 即使超级权限（auto_consent）模式也强制弹窗。其余高危（sudo / 管道执行 /
        # eval / chmod 777 / env dump / secret 引用）在超级模式下自动放行——
        # 见 agent loop 对 auto_approve 的处理。
        #
        # 例外：rm 操作目标全部在 /tmp/ 下时视为安全（临时文件清理），不弹窗。
        cmd = command or ""
        if not _DESTRUCTIVE_RE.search(cmd):
            return False
        if _is_rm_tmp_only(cmd):
            return False
        return True
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 120). Use higher values (300-600) for package installs (brew/pip/apt).",
                "default": 120,
            },
        },
        "required": ["command"],
    }

    @staticmethod
    def _missing_bin_hint(command: str) -> str | None:
        """命令引用了已知的外部 CLI 但系统未安装时，返回友好安装引导；否则 None。

        只在该 CLI 作为独立 token 出现（首尾为空白/串边界）时才判定，避免误伤
        路径 / 参数里的子串。命中后由 run() 直接返回引导，不执行命令。
        """
        for bin_name, hint in _MISSING_BIN_HINTS.items():
            if re.search(rf"(?<!\S){re.escape(bin_name)}(?!\S)", command) and shutil.which(bin_name) is None:
                return hint
        return None

    async def run(self, command: str, timeout: int = 120) -> str:
        # 拦截直接访问 .secrets 目录的命令——密钥只能通过 list_secrets / get_secret 访问
        if ".secrets" in command:
            return (
                "Error: 禁止通过 shell 访问 .secrets 目录。"
                "密钥只能通过 list_secrets / get_secret 工具访问。"
                "如果密钥不存在，请提示用户用 set_secret 配置。"
            )
        # 缺失外部 CLI 依赖时给出安装引导，而不是让用户拿到晦涩的 "command not found"
        missing_hint = self._missing_bin_hint(command)
        if missing_hint:
            return missing_hint
        try:
            # 把 .secrets/*.env 的 KEY=value 注入子进程环境，脚本里可直接用 $KEY，
            # 模型上下文里从不出现明文。注入失败不影响命令执行。
            env = dict(os.environ)
            try:
                from ethan.core.secrets_store import load_secret_env
                env.update(load_secret_env())
            except Exception:
                pass
            # start_new_session=True 使子进程成为新会话/进程组的 leader，
            # 这样 os.killpg 可以一把杀掉整个进程组（包括 shell 派生的孙进程），
            # 避免 proc.kill() 只杀 shell 本身、子进程（python/管道/&后台）继续跑的问题。
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=os.path.expanduser("~"),  # 默认 home 目录，避免 launchd 下 cwd 为 /
                start_new_session=True,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace").strip()
            # 不截断，让模型自己判断哪些有用（shell 有 no_compress=True，不会被压缩）
            return output or "(no output)"
        except asyncio.TimeoutError:
            # 超时后必须 kill 整个进程组，避免僵尸进程（如 osascript 弹权限框一直挂起）
            _kill_process_group(proc)
            return f"Command timed out after {timeout}s"
        except asyncio.CancelledError:
            # 用户取消工具调用时，kill 整个进程组，避免孙进程残留
            _kill_process_group(proc)
            raise
