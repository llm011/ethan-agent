# 原生 reasoning 与真实 wire 历史

UI 的一条 assistant 消息可以包含多轮工具和多段正文，不能直接当作模型协议中的一个
assistant/tool 对。原生循环将每次实际生成的 assistant、对应 tool_call_id 和工具结果，
分别保存为 `_wire_transcript`。reasoning 属于那一次生成，不跨轮拼给另一组工具调用。
内部虚拟 `decide` 不作为已派发的真实工具保存。

`message_wire_transcripts(message_id, session_id, state)`（state JSON 内保存 transcript） 与最终 UI Message 在同一
独立连接事务中写入，BEGIN IMMEDIATE 后完整 commit/rollback；其他共享连接 touch/commit
不能提交半成品消息。SessionStore.load 按消息 ID 附回私有 wire，下一请求入口展开完整
配对轮次；不完整的工具轮次不伪造结果。无 wire 的旧消息仍保留旧行为。

StreamCollector 的末轮 reasoning 供 UI Message 显示，完整逐轮 reasoning 另由 transcript
保存。此模块不自动创建运行占位、不提供每 iteration 崩溃检查点；持久运行生命周期在
计划条目6实现。

职责拆分同时将超长 SessionStore 和 producer 按 schema/messages/assets/metadata/query/
maintenance、native/delegate/browser/helpers 拆分；旧导入与 monkeypatch 门面保持兼容。

验证：`tests/test_wire_persistence.py` 执行真实 Agent→producer→SQLite→新请求，严格检查
每轮 reasoning/tool-call-id 配对；相关独立套件82项通过。旧过时源码路径契约测试应跟随
职责模块，不能为通过测试在门面添加假的迁移或 done 字符串。

真实已配置 deepseek-v4.1-flash 网关两步工具调用均未报400，但探针普通/显式thinking均未返回
非空 reasoning，因此只证明两步可用，不冒充非空 thinking 字段线上回传验收。
