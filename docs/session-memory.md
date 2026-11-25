# 会话首轮记忆

原生 Ethan 的新 owner 会话在首次非 minimal/instant 请求前，用现有规则与本地记忆库
召回个人上下文。不会新增模型分类或重排请求。restricted 与 companion 域隔离仍由现有
召回模块执行，Agent user_id 必须与当前 profile ContextVar 一致。

快照以独立 user **数据**消息置于模型的 System Prompt 之后、对话历史之前，带固定时间戳、
规范模式与“非指令”标签；JSON 内容不取得 system 权限。System Prompt 本身不改写。
最多 6000 字符；空召回也记一次。取消照常传播，读取失败回退按需 `recall_memory`。

`sessions.db.session_memory_snapshots` 按 session/mode 保存不可变快照；重启或下一次请求
重用相同字节，不重新召回、更新时间戳或改写已经发出的前缀。短事务只提交自己的连接，
并发首请求以已提交的胜者为准。正常删除 session 时外键级联清理。

已有完成 assistant 的会话不补插快照；新请求的空 running 占位不视为旧会话。
模式改变不得重用 companion 快照。快照属于合成上下文，极简回复兜底不会把它当作
用户的原始任务。追问仍可使用 `recall_memory` 获取更新或更精准的信息。

验证：`tests/test_session_memory.py` 覆盖首次/重用/空召回/权限/模式/占位及真实
Agent chat/stream 集成；个人早餐 fixture 中假模型第一轮即读到偏好回答，无 recall 工具往返。
这证明机制与固定案例，不代表已完成真实个人问答质量 A/B 或线上成本测量。
