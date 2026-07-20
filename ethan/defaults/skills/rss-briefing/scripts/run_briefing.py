#!/usr/bin/env python3
"""
RSS Briefing Engine v4.0

修复 v3.0 的核心 bug：
  1. 主脚本完全无代理支持（导致大量海外源抓取失败）
  2. User-Agent 过短被部分源拒绝
  3. 错误信息未带 source url，难以排查
  4. XML 解析无容错，单条坏源会让整个流程崩
  5. HASH_FILE / SOURCE_FILE 路径在不同脚本间不一致

代理配置：export HTTPS_PROXY=http://127.0.0.1:7890
        export HTTP_PROXY=http://127.0.0.1:7890
        export ALL_PROXY=http://127.0.0.1:7890

依赖：仅 Python 标准库（urllib.request + xml.etree.ElementTree）。
"""

import hashlib
import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------
# 1. 配置与路径初始化
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 脚本位于 scripts/ 下，技能根目录是其父目录
SKILL_DIR = os.path.dirname(BASE_DIR)

# 哈希文件位置（按优先级回退）：
#   1) $ETHAN_MEMORY_DIR/rss_sent_hashes.json  —— 显式指定（推荐用于容器/CI）
#   2) ~/.ethan/memory/rss_sent_hashes.json    —— ethan 默认安装位置
#   3) <skill_dir>/memory/rss_sent_hashes.json —— 技能内置（最可移植，但 skill 升级时可能丢）
def _resolve_hash_file():
    env_dir = os.environ.get('ETHAN_MEMORY_DIR')
    if env_dir:
        return os.path.join(env_dir, 'rss_sent_hashes.json')
    home_ethan = os.path.expanduser('~/.ethan/memory')
    if os.path.isdir(os.path.expanduser('~/.ethan')):
        return os.path.join(home_ethan, 'rss_sent_hashes.json')
    return os.path.join(SKILL_DIR, 'memory', 'rss_sent_hashes.json')

HASH_FILE = _resolve_hash_file()
SOURCE_FILE = os.path.join(SKILL_DIR, 'rss_sources.json')

# 每个源最多抓取的条目数（V2 公平展示原则）
PER_SOURCE_LIMIT = 3
# 单源抓取超时（秒）
FETCH_TIMEOUT = 15
# 仅抓取最近 N 天内的条目
RECENT_DAYS = 3

# 完整的桌面 Chrome UA，避免被反爬拒绝
USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)

# ---------------------------------------------------------
# 2. SSL 与代理
# ---------------------------------------------------------
# 禁用 SSL 验证：部分自签名或证书链不完整的 RSS 源需要绕过。
# 注意：CERT_NONE 会带来中间人风险，仅在受信任的网络/代理环境下使用。
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def build_opener():
    """根据环境变量构建带代理支持的 urllib opener。

    优先级：HTTPS_PROXY / HTTP_PROXY / ALL_PROXY。
    未设置任何代理变量时，返回直连 opener。
    """
    https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    all_proxy = os.environ.get('ALL_PROXY') or os.environ.get('all_proxy')

    proxies = {}
    if https_proxy:
        proxies['https'] = https_proxy
    if http_proxy:
        proxies['http'] = http_proxy
    if all_proxy:
        # ALL_PROXY 作为兜底
        proxies.setdefault('https', all_proxy)
        proxies.setdefault('http', all_proxy)

    handlers = []
    if proxies:
        handlers.append(urllib.request.ProxyHandler(proxies))

    return urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()


# ---------------------------------------------------------
# 3. 哈希去重
# ---------------------------------------------------------
def get_url_hash(url):
    return hashlib.md5(url.strip().encode()).hexdigest()


def load_sent_hashes():
    if os.path.exists(HASH_FILE):
        try:
            with open(HASH_FILE, 'r') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_sent_hashes(hashes):
    ordered_hashes = list(hashes)
    with open(HASH_FILE, 'w') as f:
        json.dump(ordered_hashes[-3000:], f)


def load_sources():
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------
# 4. 核心抓取逻辑
# ---------------------------------------------------------
# 匹配 XML 1.0 规范中不允许出现的控制字符（0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F）
INVALID_XML_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def sanitize_xml(xml_data):
    """剔除 XML 中不合法的控制字符，避免 ET.fromstring 解析失败。"""
    if isinstance(xml_data, bytes):
        # 先尝试按 utf-8 解码；失败时退到 latin-1 兜底
        try:
            text = xml_data.decode('utf-8')
        except UnicodeDecodeError:
            text = xml_data.decode('latin-1', errors='replace')
    else:
        text = xml_data
    return INVALID_XML_CHARS_RE.sub('', text).encode('utf-8')


def fetch_feed(url, source_name, category, sent_hashes, limit=PER_SOURCE_LIMIT):
    entries = []
    opener = build_opener()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})

        with opener.open(req, timeout=FETCH_TIMEOUT) as response:
            xml_data = response.read()

        # 容错：先清理控制字符再解析
        try:
            root = ET.fromstring(sanitize_xml(xml_data))
        except ET.ParseError as e:
            print(f"  ✗ {source_name} | {url} | XML 解析失败: {e}", file=sys.stderr)
            return entries

        is_atom = 'atom' in root.tag.lower() or root.tag.endswith('feed')
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        if is_atom:
            items = root.findall('.//atom:entry', ns) or \
                    root.findall('.//{http://www.w3.org/2005/Atom}entry')
        else:
            items = root.findall('.//item')

        count = 0
        for item in items:
            if count >= limit:
                break

            title = (item.findtext('.//title') or
                     item.findtext('.//{http://www.w3.org/2005/Atom}title') or
                     '无标题').strip()

            link = ''
            link_elem = item.find('.//link')
            if link_elem is None:
                link_elem = item.find('.//{http://www.w3.org/2005/Atom}link')
            if link_elem is not None:
                link = (link_elem.get('href') or link_elem.text or '').strip()
            # RSS 2.0 的 link 是文本节点
            if not link:
                link = (item.findtext('link') or '').strip()

            if not link or get_url_hash(link) in sent_hashes:
                continue

            summary = (item.findtext('.//description') or
                       item.findtext('.//summary') or
                       item.findtext('.//{http://www.w3.org/2005/Atom}summary') or '').strip()

            # 简单清洗 HTML
            summary = re.sub(r'<[^>]+>', ' ', summary)
            summary = " ".join(summary.split())[:500]

            entries.append({
                'title': title,
                'link': link,
                'raw_summary': summary,
                'source': source_name,
                'category': category,
                'hash': get_url_hash(link)
            })
            count += 1

    except urllib.error.HTTPError as e:
        print(f"  ✗ {source_name} | {url} | HTTP {e.code}: {e.reason}", file=sys.stderr)
    except urllib.error.URLError as e:
        # 代理握手失败、DNS 失败、超时等都归到这里
        print(f"  ✗ {source_name} | {url} | URL 错误: {e.reason}", file=sys.stderr)
    except socket.timeout:
        print(f"  ✗ {source_name} | {url} | 超时 (>{FETCH_TIMEOUT}s)", file=sys.stderr)
    except ssl.SSLError as e:
        print(f"  ✗ {source_name} | {url} | SSL 错误: {e}", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ {source_name} | {url} | 未知错误: {type(e).__name__}: {e}", file=sys.stderr)
    return entries


# ---------------------------------------------------------
# 5. 简报生成
# ---------------------------------------------------------
def generate_briefing():
    try:
        sources = load_sources()
    except FileNotFoundError:
        return f"❌ 找不到订阅源文件: {SOURCE_FILE}"
    except json.JSONDecodeError as e:
        return f"❌ 订阅源文件 JSON 解析失败: {e}"

    sent_hashes = load_sent_hashes()
    new_hashes = set()
    all_entries = []
    failed_count = 0

    # 代理状态提示（便于排查）
    proxy_used = (
        os.environ.get('HTTPS_PROXY') or
        os.environ.get('HTTP_PROXY') or
        os.environ.get('ALL_PROXY') or
        '(直连，未配置代理)'
    )
    print(f"🚀 启动 RSS Briefing Engine v4.0 (proxy={proxy_used})", file=sys.stderr)
    print(f"   共 {len(sources)} 个订阅源，每源最多 {PER_SOURCE_LIMIT} 条", file=sys.stderr)

    for src in sources:
        category = src.get('category', '未分类')
        found = fetch_feed(src['url'], src['name'], category, sent_hashes, limit=PER_SOURCE_LIMIT)
        if found:
            all_entries.extend(found)
            for f in found:
                new_hashes.add(f['hash'])
        else:
            failed_count += 1

    if not all_entries:
        return f"📭 今日暂无新增资讯（已过滤已读）。{failed_count} 个源抓取失败/无新内容，详见 stderr。"

    # 构建输出文本
    report = []
    report.append(f"📰 RSS 深度简报 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append("=" * 50 + "\n")

    # 按分类组织
    cats = {}
    for e in all_entries:
        cats.setdefault(e['category'], []).append(e)

    for cat in sorted(cats.keys()):
        report.append(f"📂 【{cat}】")
        report.append("-" * 20)
        for item in cats[cat]:
            report.append(f"● {item['title']} ({item['source']})")
            report.append(f"  链接: {item['link']}")
            if item['raw_summary']:
                report.append(f"  摘要线索: {item['raw_summary'][:300]}")
            report.append("")

    report.append("=" * 50)
    report.append(f"📊 统计: 本次共捕获 {len(all_entries)} 条全新动态，{failed_count} 个源失败。")

    # 只有生成了内容才保存哈希
    if all_entries:
        save_sent_hashes(sent_hashes.union(new_hashes))

    return "\n".join(report)


if __name__ == '__main__':
    content = generate_briefing()
    print("-----START_RAW_BRIEFING-----")
    print(content)
    print("-----END_RAW_BRIEFING-----")
