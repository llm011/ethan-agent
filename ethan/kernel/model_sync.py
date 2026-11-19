"""外部内核按会话模型同步与匹配。

用户在聊天框切换模型时（只对当前会话 / 请求生效，绝不修改全局配置）：
  1. 解析请求模型 `raw`（支持 `id`、`provider/id` 或 `config.models` 里配置的 alias）；
  2. 在目标内核**自身可用的模型集合**里查找对应模型（精确匹配优先，其次忽略大小写
     与 `.`/`-` 差异，例如 `claude-sonnet-4.6` ↔ `claude-sonnet-4-6`）；
  3. 找到了才在本轮 / 本会话切换过去；找不到则保持外部内核自身默认模型，避免硬传
     一个内核不认识的模型导致整轮对话失败。

各内核实现方式：
  - ACP 内核（DSH / OpenCode / Antigravity）：在 `new_session()` 返回的 `config_options`
    （`category=="model"` 或 `id=="model"`）里查找并调用 `conn.set_config_option()`；
  - Pi：从 `pi --list-models` 发现可用 `(provider, model)`，命中时传 `--model provider/model`；
  - Claude Code：从 `~/.claude/settings(.local).json`、可选代理 `/v1/models` 与 Claude
    原生模型族中匹配，命中时传 `--model <id>`；
  - Codex：从 `$CODEX_HOME/config.toml`、可选自定义 provider `/models` 与 OpenAI 模型族
    中匹配，命中时传 `-m <id>`。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 60.0
_pi_cache: dict[str, tuple[float, list[tuple[str, str]]]] = {}
_http_models_cache: dict[str, tuple[float, list[str]]] = {}


@dataclass(frozen=True)
class ModelRef:
    """解析后的请求模型引用。"""

    raw: str
    provider: str
    model_id: str


@dataclass(frozen=True)
class ModelCandidate:
    """外部内核提供的一个可选模型条目。"""

    value: str
    provider: str = ""
    model_id: str = ""
    name: str = ""
    priority: int = 0


def _norm_id(text: str) -> str:
    """规范化模型 ID：忽略大小写，并把 `.` 与 `-` 视为等价（如 4.6 ↔ 4-6）。"""
    return (text or "").strip().lower().replace(".", "-")


def parse_model_ref(raw: str) -> ModelRef | None:
    """把聊天框传入的 `raw`（id / provider/id / alias）解析为 `(provider, model_id)`。"""
    text = (raw or "").strip()
    if not text:
        return None

    try:
        from ethan.core.config import get_config

        entry = get_config().get_model(text)
        if entry is not None:
            return ModelRef(raw=text, provider=entry.provider or "", model_id=entry.id or text)
    except Exception:
        pass

    if "/" in text:
        prov, _, mid = text.partition("/")
        return ModelRef(raw=text, provider=prov.strip(), model_id=mid.strip())
    return ModelRef(raw=text, provider="", model_id=text)


def match_model_candidate(
    target: ModelRef,
    candidates: list[ModelCandidate],
) -> ModelCandidate | None:
    """在候选中寻找最匹配 `target` 的一项；找不到返回 None。

    匹配层级（数字越小优先级越高）：
      0: `target.provider` 精确匹配 + `model_id` 精确匹配（忽略大小写）
      1: `cand.value` 与 `target.raw` 完全一致（忽略大小写）
      2: `cand.model_id` 或 `cand.name` 与 `target.model_id` 完全一致（忽略大小写）
      3: `target.provider` 精确匹配 + `_norm_id(model_id)` 一致
      4: `_norm_id(model_id)` 或 `_norm_id(name)` 一致
    同层级按 `(priority 更高, 原列表顺序更靠前)` 择优。
    """
    if not candidates:
        return None

    t_raw = target.raw.lower()
    t_prov = target.provider.lower()
    t_mid = target.model_id.lower()
    t_mid_norm = _norm_id(target.model_id)

    best_key: tuple[int, int, int] | None = None
    best_cand: ModelCandidate | None = None

    for idx, cand in enumerate(candidates):
        c_val = (cand.value or "").strip().lower()
        c_prov = (cand.provider or "").strip().lower()
        c_mid = (cand.model_id or "").strip().lower()
        c_name = (cand.name or "").strip().lower()

        tier: int | None = None
        if t_prov and c_prov == t_prov and c_mid == t_mid:
            tier = 0
        elif c_val == t_raw:
            tier = 1
        elif (c_mid and c_mid == t_mid) or (c_name and c_name == t_mid) or (c_name and c_name == t_raw):
            tier = 2
        elif t_prov and c_prov == t_prov and _norm_id(c_mid) == t_mid_norm:
            tier = 3
        elif (c_mid and _norm_id(c_mid) == t_mid_norm) or (c_name and _norm_id(c_name) == t_mid_norm):
            tier = 4

        if tier is None:
            continue

        # tier 越小越好；同 tier 下 provider 命中加分、priority 越大越好、idx 越小越好
        prov_bonus = 0 if (t_prov and c_prov == t_prov) else 1
        rank_key = (tier, prov_bonus, -cand.priority, idx)
        if best_key is None or rank_key < best_key:
            best_key = rank_key
            best_cand = cand

    return best_cand


def _parse_acp_option_fields(value: str, group: str = "") -> tuple[str, str]:
    """从 ACP select option 的 value 拆出 `(provider, model_id)`。

    兼容三种常见格式：
      - DSH JSON 数组：`'["deepseek-official","deepseek-v4-pro"]'`
      - OpenCode 斜杠格式：`'cliproxy/claude-sonnet-4.6'`
      - 裸模型 ID：`'gpt-5.4'`
    """
    val = (value or "").strip()
    if val.startswith("["):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list) and len(parsed) >= 2:
                return str(parsed[0] or ""), str(parsed[1] or "")
        except Exception:
            pass
    if "/" in val:
        prov, _, mid = val.partition("/")
        return prov.strip(), mid.strip()
    return group.strip(), val


def match_acp_model_option(
    requested: str,
    config_options: list[Any],
    *,
    preferred_group: str = "",
) -> tuple[str, str, str] | None:
    """在 ACP `new_session` 返回的 `config_options` 中查找匹配 `requested` 的模型选项。

    返回 `(config_id, option_value, current_value)`；未找到或不存在 model 配置项时返回 None。
    """
    target = parse_model_ref(requested)
    if target is None or not config_options:
        return None

    model_opt = None
    for opt in config_options:
        cat = (getattr(opt, "category", None) or "").strip().lower()
        oid = (getattr(opt, "id", None) or "").strip().lower()
        if cat == "model" or oid == "model":
            model_opt = opt
            break
    if model_opt is None:
        return None

    config_id = str(getattr(model_opt, "id", "") or "model")
    current_value = str(getattr(model_opt, "current_value", "") or "")
    raw_options = getattr(model_opt, "options", None) or []

    candidates: list[ModelCandidate] = []
    for entry in raw_options:
        # SessionConfigSelectGroup 含 group + options；SessionConfigSelectOption 含 value + name
        nested = getattr(entry, "options", None)
        if isinstance(nested, list):
            grp = str(getattr(entry, "group", "") or "")
            prio = 10 if (preferred_group and grp == preferred_group) else 0
            for sub in nested:
                val = str(getattr(sub, "value", "") or "")
                name = str(getattr(sub, "name", "") or "")
                c_prov, c_mid = _parse_acp_option_fields(val, group=grp)
                candidates.append(
                    ModelCandidate(
                        value=val,
                        provider=c_prov,
                        model_id=c_mid,
                        name=name,
                        priority=prio,
                    )
                )
        else:
            val = str(getattr(entry, "value", "") or "")
            name = str(getattr(entry, "name", "") or "")
            c_prov, c_mid = _parse_acp_option_fields(val)
            prio = 10 if (preferred_group and c_prov == preferred_group) else 0
            candidates.append(
                ModelCandidate(
                    value=val,
                    provider=c_prov,
                    model_id=c_mid,
                    name=name,
                    priority=prio,
                )
            )

    matched = match_model_candidate(target, candidates)
    if matched is None:
        return None
    return config_id, matched.value, current_value


# ── Pi 模型发现 ──────────────────────────────────────────────────


def parse_pi_list_models(output: str) -> list[tuple[str, str]]:
    """解析 `pi --list-models` 表格输出为 `(provider, model)` 列表。"""
    rows: list[tuple[str, str]] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0].lower() == "provider" and parts[1].lower() == "model":
            continue
        if set(parts[0]) <= {"-"}:
            continue
        rows.append((parts[0], parts[1]))
    return rows


async def list_pi_models(binary: str = "pi") -> list[tuple[str, str]]:
    """执行 `pi --list-models` 并缓存 60s；失败返回空列表。"""
    now = time.monotonic()
    cached = _pi_cache.get(binary)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]

    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "--list-models",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        combined = "\n".join(
            p for p in (stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")) if p
        )
        rows = parse_pi_list_models(combined)
        _pi_cache[binary] = (now, rows)
        return rows
    except Exception:
        logger.debug("探测 Pi 模型列表失败", exc_info=True)
        return []


async def resolve_pi_model(requested: str, *, binary: str = "pi") -> str | None:
    """在 Pi 可用模型列表里查找对应模型，命中返回 `provider/model`，否则 None。"""
    target = parse_model_ref(requested)
    if target is None:
        return None
    rows = await list_pi_models(binary)
    if not rows:
        return None
    candidates = [
        ModelCandidate(value=f"{prov}/{mid}", provider=prov, model_id=mid, name=mid)
        for prov, mid in rows
    ]
    matched = match_model_candidate(target, candidates)
    return matched.value if matched else None


# ── HTTP /models 探测（用于自定义代理，短超时 + 缓存，失败不阻断）──────────


async def _fetch_openai_models_list(
    url: str,
    api_key: str = "",
) -> list[str]:
    """查询 OpenAI 兼容 `/models` 端点返回模型 ID 列表；失败一律返回空列表。"""
    cache_key = f"{url}|{bool(api_key)}"
    now = time.monotonic()
    cached = _http_models_cache.get(cache_key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]

    try:
        import httpx

        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["x-api-key"] = api_key
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                _http_models_cache[cache_key] = (now, [])
                return []
            payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        ids: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
        _http_models_cache[cache_key] = (now, ids)
        return ids
    except Exception:
        _http_models_cache[cache_key] = (now, [])
        return []


# ── Claude Code 模型发现 ──────────────────────────────────────────


_CLAUDE_ALIASES = ("sonnet", "opus", "haiku")


def _read_claude_settings_models(claude_dir: Path | None = None) -> tuple[list[str], str, str]:
    """从 `~/.claude/settings(.local).json` 读取配置的模型名、base_url 与 token。"""
    base_dir = claude_dir or (Path.home() / ".claude")
    models: list[str] = []
    base_url = ""
    api_key = ""

    for fname in ("settings.json", "settings.local.json"):
        p = base_dir / fname
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        top_model = data.get("model")
        if isinstance(top_model, str) and top_model.strip():
            models.append(top_model.strip())

        avail = data.get("availableModels")
        if isinstance(avail, list):
            for item in avail:
                if isinstance(item, str) and item.strip():
                    models.append(item.strip())

        env = data.get("env")
        if isinstance(env, dict):
            for k in (
                "ANTHROPIC_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_SMALL_FAST_MODEL",
            ):
                v = env.get(k)
                if isinstance(v, str) and v.strip():
                    models.append(v.strip())
            if isinstance(env.get("ANTHROPIC_BASE_URL"), str) and env["ANTHROPIC_BASE_URL"].strip():
                base_url = env["ANTHROPIC_BASE_URL"].strip()
            for tk in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
                if isinstance(env.get(tk), str) and env[tk].strip():
                    api_key = env[tk].strip()
                    break

    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq, base_url, api_key


async def resolve_claude_model(
    requested: str,
    *,
    claude_dir: Path | None = None,
    probe_remote: bool = True,
) -> str | None:
    """判断 Claude Code 是否拥有对应模型；有则返回用于 `--model` 的模型名，否则 None。"""
    target = parse_model_ref(requested)
    if target is None:
        return None

    settings_models, base_url, api_key = _read_claude_settings_models(claude_dir)
    live_models: list[str] = []
    if probe_remote and base_url:
        ep = base_url.rstrip("/")
        models_url = f"{ep}/models" if ep.endswith("/v1") else f"{ep}/v1/models"
        live_models = await _fetch_openai_models_list(models_url, api_key=api_key)

    known: list[str] = []
    for m in (*settings_models, *live_models, *_CLAUDE_ALIASES):
        if m not in known:
            known.append(m)

    candidates = [ModelCandidate(value=m, model_id=m, name=m) for m in known]
    matched = match_model_candidate(target, candidates)
    if matched is not None:
        return matched.value

    # 未拿到远端实时列表时（如直连 Anthropic 官方），Claude Code 原生支持 claude-* 全名
    if not live_models and target.model_id.lower().startswith("claude-"):
        return target.model_id
    return None


# ── Codex 模型发现 ────────────────────────────────────────────────


_OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4", "codex-")


def _read_codex_config_models(codex_home: Path | None = None) -> tuple[list[str], str, str, str]:
    """从 `$CODEX_HOME/config.toml` 读取已知模型、激活 provider、base_url 与 token。"""
    home = codex_home or Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    cfg_path = home / "config.toml"
    models: list[str] = []
    active_provider = ""
    base_url = ""
    api_key = ""

    if cfg_path.is_file():
        try:
            import tomllib

            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            top_model = data.get("model")
            if isinstance(top_model, str) and top_model.strip():
                models.append(top_model.strip())
            active_provider = str(data.get("model_provider") or "").strip()

            profiles = data.get("profiles")
            if isinstance(profiles, dict):
                for pcfg in profiles.values():
                    if isinstance(pcfg, dict) and isinstance(pcfg.get("model"), str):
                        m = pcfg["model"].strip()
                        if m:
                            models.append(m)

            notice = data.get("notice")
            if isinstance(notice, dict) and isinstance(notice.get("model_migrations"), dict):
                for k, v in notice["model_migrations"].items():
                    for item in (k, v):
                        if isinstance(item, str) and item.strip():
                            models.append(item.strip())

            providers = data.get("model_providers")
            if isinstance(providers, dict) and active_provider and active_provider in providers:
                pcfg = providers[active_provider]
                if isinstance(pcfg, dict):
                    base_url = str(pcfg.get("base_url") or "").strip()
                    env_key = str(pcfg.get("env_key") or "").strip()
                    if env_key:
                        api_key = os.environ.get(env_key, "")

    if not api_key:
        auth_path = home / "auth.json"
        if auth_path.is_file():
            try:
                auth_data = json.loads(auth_path.read_text(encoding="utf-8"))
                if isinstance(auth_data, dict):
                    api_key = str(
                        auth_data.get("OPENAI_API_KEY")
                        or auth_data.get("access_token")
                        or ""
                    ).strip()
            except Exception:
                pass

    seen: set[str] = set()
    uniq: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq, active_provider, base_url, api_key


async def resolve_codex_model(
    requested: str,
    *,
    codex_home: Path | None = None,
    probe_remote: bool = True,
) -> str | None:
    """判断 Codex 是否拥有对应模型；有则返回用于 `-m` 的模型名，否则 None。"""
    target = parse_model_ref(requested)
    if target is None:
        return None

    cfg_models, active_provider, base_url, api_key = _read_codex_config_models(codex_home)
    live_models: list[str] = []
    if probe_remote and base_url:
        ep = base_url.rstrip("/")
        models_url = f"{ep}/models" if ep.endswith("/v1") else f"{ep}/v1/models"
        live_models = await _fetch_openai_models_list(models_url, api_key=api_key)

    known: list[str] = []
    for m in (*cfg_models, *live_models):
        if m not in known:
            known.append(m)

    candidates = [ModelCandidate(value=m, model_id=m, name=m) for m in known]
    matched = match_model_candidate(target, candidates)
    if matched is not None:
        return matched.value

    # 使用官方 OpenAI（或未覆盖且未拿到自定义列表）时，识别标准 OpenAI / Codex 模型前缀
    if (not active_provider or active_provider.lower() == "openai") and not live_models:
        mid_low = target.model_id.lower()
        if any(mid_low.startswith(p) for p in _OPENAI_PREFIXES):
            return target.model_id
    return None


def clear_model_sync_caches() -> None:
    """清空模型探测缓存（供测试或配置变更后使用）。"""
    _pi_cache.clear()
    _http_models_cache.clear()
