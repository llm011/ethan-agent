# Home Assistant Skill 安装指引

## 方式一：使用社区 HA skill 包

```bash
# 从社区下载 HA skill（包含完整 entity 查询、场景管理等）
git clone https://github.com/homeassistant-ai/skills ~/.ethan/skills/home-assistant-full
```

安装后将其中的文件合并到 `~/.ethan/skills/home-assistant/`。

## 方式二：手动配置

### 1. 获取 HA 访问凭据

在 Home Assistant 中：
- 进入「配置」→「用户」→「长期访问令牌」→「创建令牌」
- 记录 Token 和 HA 地址（如 `http://192.168.1.x:8123`）

### 2. 配置环境变量

在 `~/.zshrc` 或 `~/.bashrc` 中加入：

```bash
export HA_URL="http://192.168.1.x:8123"
export HA_TOKEN="your_long_lived_access_token"
```

或在 Ethan 的 tools.md 中加入自定义工具描述。

### 3. 验证连接

```bash
curl -s -H "Authorization: Bearer $HA_TOKEN" $HA_URL/api/ | python3 -m json.tool
```

返回 `{"message": "API running."}` 表示连接成功。

### 4. 获取设备列表

```bash
curl -s -H "Authorization: Bearer $HA_TOKEN" $HA_URL/api/states | \
  python3 -c "import json,sys; [print(e['entity_id'], '-', e['state']) for e in json.load(sys.stdin)[:20]]"
```
