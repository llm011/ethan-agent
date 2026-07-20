# RSS 订阅源管理

所有的 RSS 订阅源都定义在 `rss_sources.json` 文件中。

## 数据格式

```json
[
  {
    "name": "订阅源名称",
    "url": "RSS 链接地址",
    "category": "分类名称 (如：技术, 金融, 资讯)"
  }
]
```

## 修改建议

1. **新增订阅源**: 直接在 JSON 数组中添加一个对象即可。
2. **分类管理**: 建议保持分类名称简洁，脚本会自动按分类进行内容组织。
3. **性能注意**: 订阅源过多会导致抓取时间变长，建议控制在 20-30 个以内。

## 已知失效源

- **nitter.net 系列**（2024-2025 期间 nitter 公共实例陆续关停）：所有 `https://nitter.net/<user>/rss` 链接均会返回 5xx 或超时。
  - 替代方案 1：自建 nitter 实例后批量替换 URL。
  - 替代方案 2：改用 RSSHub 提供的 Twitter/X 路由：`https://rsshub.app/twitter/user/<username>`。
  - 替代方案 3：直接删除这些条目。

## 调试单源

```bash
# 单独测试某个源是否可达（带代理）
curl -sL -x "$HTTPS_PROXY" -A "Mozilla/5.0" "<url>" | head -20
```
