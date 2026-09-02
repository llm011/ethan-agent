# qcc Skill

企查查智能体数据平台（https://agent.qcc.com）接入技能：通过 MCP streamable HTTP 端点实时查询中国企业全维度数据（工商 / 风险 / 知产 / 经营 / 董监高 / 历史存档 / 法规 / 司法案例 / 标讯 / 文档解析）。

- `qcc.py`：零第三方依赖的 MCP 客户端（仅 python 标准库），自带本地文件缓存（`~/.ethan/data/qcc/<公司名>/<tool>_<日期>.md`，30 天过期自动重查）。
- 鉴权：`~/.ethan/.secrets/qcc-api-key`（内容 `QCC_AUTHORIZATION=Bearer <token>`），与官方 MCP / qcc-agent-cli 共用同一个 key 与积分体系。
- 官方 CLI 备选：`npm install -g qcc-agent-cli && qcc init --authorization "Bearer <token>"`（本机调试用；容器内技能走 qcc.py 即可）。

## 快速验证

```bash
python3 qcc.py servers
python3 qcc.py call company get_company_registration_info --args '{"searchKey": "企查查科技股份有限公司"}'
python3 qcc.py call company get_company_registration_info --args '{"searchKey": "企查查科技股份有限公司"}'  # 第二次应命中缓存
```
