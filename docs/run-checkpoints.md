# 原生运行检查点与安全续跑

持久 session_id 的原生 Agent 自动建立 running 占位，进程内无会话调用不持久化。
API producer 已安装 Recorder 时复用它，不重复建立占位。每次 iteration、工具批次授权前
prepared、dispatch 与单个工具完成记录都通过独立短 SQLite 事务写入；每个完成结果在下一
工具或最终 UI 气泡之前可恢复。记录目标、轮次、todos、产物、已完成摘要、inflight 与逐轮 wire。

run_checkpoints 保存运行阶段与结构化事实；最终 Message 与独立 message_wire_transcripts
仍同事务提交。原生最终结果由进程内 pending claim 合回原占位，失败回滚保留 claim，成功
commit 后才消费。若进程恰在 checkpoint terminal 与渠道 final 保存之间被杀，仍可能留下
无成本归因的占位：不是跨进程 exactly-once 账单，不承诺该窗口已消除。

未完成工具一律 uncertain，取消不证明它没产生副作用；恢复上下文明确禁止自动重放。
只恢复完整 assistant/tool-call-id/result 配对，未知结果不能编造 tool message。
`plan_write`/`plan_update` 跟踪任务状态，成功文件产物留作只读复核线索。

Web 续跑经认证、SessionStore 当前profile查找与 interrupted 状态 CAS 认领，读取结构化
检查点后走常规 chat。完成部分可供下一请求参考，外部 CLI 内部工具和已有进程不会重连；
没有已知结果时先核验，无法核验应报告未知。进程内任务中心注册表不等于持久执行队列。

验证仅使用 owned child process 与临时数据库：真实 SIGKILL/os._exit、保存与取消回滚、
逐工具完成、真实 producer→SQLite→下一请求严格配对、错误/停止/兜底，以及原生渠道兼容。
不通过杀常驻服务制造测试，也不调用真实外部副作用工具。
