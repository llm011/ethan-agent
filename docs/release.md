# 发版流程

> 一份「踩过所有坑」的发版手册。改动版本号 / tag 格式 / 发版 workflow 之前先读这里。

## 一、版本号从哪来

**唯一来源是 `pyproject.toml` 的 `version`**，其他文件都由 CI 从它派生。

```
pyproject.toml  version = "1.0.0b25"
    │
    ├── PyPI        直接用（PEP 440）
    ├── Desktop     PEP440 → semver 转换后写进 tauri.conf.json
    ├── Android     Gradle 从 pyproject 读取
    └── Docker      镜像 tag
```

### 三种版本格式必须对齐

| 生态 | 格式 | `1.0.0b25` 的取值 |
|---|---|---|
| PyPI（PEP 440） | `1.0.0b25` | 原样 |
| Tauri（semver） | `1.0.0-beta.25` | CI 自动转换 |
| Windows MSI | 只能纯数字 | **不打 MSI**（见下） |

> **教训**：`1.0.0b1` 曾被直接写进 `tauri.conf.json`，Tauri 报
> `must be a semver string`，桌面端连续 3 个版本发不出去。

---

## 二、发版怎么触发

**推 `v*` tag 触发四条流水线**：

```bash
# 1. 确认版本
grep '^version' pyproject.toml

# 2. 打 tag（tag 名 = v + 版本号，必须带 v）
git tag v1.0.0b25
git push origin v1.0.0b25
```

触发的 workflow：

| Workflow | 产物 |
|---|---|
| `publish-pypi.yml` | PyPI 包 |
| `publish-desktop.yml` | macOS arm64/x64 + Windows NSIS + `latest.json` |
| `publish-docker.yml` | `ghcr.io/llm011/ethan-agent` 镜像 |
| `android.yml` | `app-release.apk` + `.sha256` |

### 自动 bump

合并到 main 会触发 `auto-bump-version.yml`，**patch 号自动 +1 并打 tag**，
所以大多数情况不需要手动发版。

> **预发布版本**（`1.0.0b25`）会自动变成 `1.0.0b26`，不会跨到正式版。
> 升正式版是人工决策。

---

## 三、已知的坑（都踩过）

### 1. 桌面端：三个平台并行构建，`latest.json` 互相覆盖

**症状**：某个平台收不到更新，报
`None of the fallback platforms [...] were found`

**原因**：三个 build job 各自生成 `latest.json` 上传覆盖，最后写完的赢。

**现状**：已修（#474）。三个 job 都设 `uploadUpdaterJson: false`，
只上传安装包和 `.sig`；`fix-updater-json` 在全部完成后**一次性合成**完整清单。

**兜底**：`fix-updater-json` 里还有 `rebuild_platform()`，
能从 `.exe` + `.exe.sig` 反推重建缺失的平台条目。

### 2. Windows MSI 拒绝非数字预发布标识

```
optional pre-release identifier in app version must be numeric-only
and cannot be greater than 65535 for msi target
```

**现状**：Windows 只打 NSIS（`--bundles nsis`），不产 MSI。
仓库的 updater 本来就 `updaterJsonPreferNsis: true`，MSI 是多余产物。

### 3. GitHub API 瞬时超时导致产物缺失

arm64 构建曾因 `Connect Timeout Error api.github.com:443` 失败，
但矩阵 `fail-fast: false`，x64 成功 → 整体显示 failure 却没人注意，
release 照常发出**只有一半平台**的版本。

**现状**：构建失败自动重试一次；发布后校验 `latest.json` 必须覆盖
`darwin-aarch64` / `darwin-x86_64` / `windows-x86_64`。

### 4. PyPI 不允许覆盖同名版本

```
400 File already exists ('ethan_agent-1.0.0b1-py3-none-any.whl')
```

**重新发同一版本必须换版本号**。tag 重推没用——PyPI 上已经有了。

### 5. tag 名必须带 `v` 前缀

所有 workflow 的触发条件都是 `tags: ['v*']`。`1.0.0b25` 不带 v 不会触发。

---

## 四、客户端怎么检测更新

### 桌面端（Tauri updater）

```
endpoints:
  https://github.com/llm011/ethan-agent/releases/latest/download/latest.json
  https://llm011.github.io/ethan-agent/latest.json     ← 备用镜像
```

- 启动 5 秒后检查，之后每小时一次
- 检测到就**后台静默下载**，完成后提示「重启安装」
- 下载有 5 分钟超时；状态卡死 6 分钟会自动重置

### Android

```
https://api.github.com/repos/llm011/ethan-agent/releases/latest
```

- 启动 30 秒后检查，**节流 30 分钟**（原为 4 小时，比发版间隔还长）
- 只在**成功**检查后记录时间戳（失败立刻允许重试）
- 手动检查不受节流限制

#### 版本比较必须支持 PEP 440 无横杠写法

```kotlin
// 1.0.0b25 → numeric=[1,0,0], pre="b25"
// 旧实现只按 '-' 拆，"0b25".toIntOrNull() 失败变 0
// → b7 和 b10 都变成 [1,0,0] + pre="" → 判定相等 → 永远收不到更新
```

---

## 五、发版后自检清单

```bash
# 1. 四条流水线都绿
gh run list --limit 5 --json workflowName,conclusion

# 2. latest.json 平台齐全（6 个）
gh release download vX.Y.Z -p latest.json -O /tmp/lj.json --clobber
python3 -c "import json;d=json.load(open('/tmp/lj.json'));print(sorted(d['platforms']))"

# 3. APK 存在
gh release view vX.Y.Z --json assets | grep -o 'app-release.apk'

# 4. 线上清单可访问
curl -sL https://github.com/llm011/ethan-agent/releases/latest/download/latest.json | head -c 200

# 5. Pages 镜像同步
curl -sL https://llm011.github.io/ethan-agent/latest.json | head -c 200
```

**期望的 `platforms`**：

```json
["darwin-aarch64", "darwin-aarch64-app", "darwin-x86_64",
 "darwin-x86_64-app", "windows-x86_64", "windows-x86_64-nsis"]
```

缺任何一个 → 对应平台的用户收不到更新。

---

## 六、改发版流程时的注意事项

1. **别在并行 job 里各自上传 `latest.json`** —— 必然互相覆盖
2. **PEP 440 与 semver 必须在边界转换**，不能指望一边兼容另一边
3. **`fail-fast: false` 的矩阵要单独检查每个 job**，否则「部分失败」会被忽略
4. **改完 workflow 必须真跑一次 tag 验证**，语法通过不代表逻辑对
5. **客户端版本比较要有测试** —— 这类 bug 只在特定版本号格式下暴露，
   单测覆盖 `b7` / `b10` / `beta.7` / 正式版 各写一遍
