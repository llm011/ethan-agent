# 回复流恢复与消息身份

Web / Desktop 共用 `packages/shared/src/chat/stream-message.ts` 的纯身份更新规则。
恢复回放时，历史可能已经含主回复的服务器数字 ID，而流仍创建临时占位；
定稿只归并本流占位 ID 与 done 明确给出的 message_id（不依赖 usage，内部续接同样读取），
保留服务器行的位置、时间与未回放的正文/过程记录/卡片元数据；流实际生成的新字段优先。
排队的增量 updater 使用事件时正文和卡片数组快照，不受后续数组追加影响。
合法旁路 assistant、不同轮正文相同但 ID 不同的消息均保留，不按正文全局去重。

无活跃 run 的断线恢复会拉最近一页。写入 fresh page 前终结刷新调度并取消 rAF/定时器；
已交付的迟到回调也不能重新插入占位或覆盖定稿。正常结束及 AbortError 收尾同样关闭调度。
React 延迟执行的合法增量 updater 使用事件时快照，之后定稿纯 updater 统一归并身份。

回归测试：`desktop/tests/stream-replay-identity.spec.ts` 静态导入双端实际 consumeStream，
覆盖服务器主行与占位共存、延迟 updater、合法旁路、不同轮相同正文，以及 fresh-page
返回后的迟到 rAF/定时器。测试无模型调用、生产数据库访问或真实浏览器凭据。

这些是源码可构造的剩余失败路径，不证明某次用户报告的具体会话命中了它们。
会话 A→B→A 的旧流所有权及全局 streaming/交互状态隔离仍需独立处理；本修复不改变该语义。
