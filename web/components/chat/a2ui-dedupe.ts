// A2UI envelope 的 surfaceId 去重：同一条消息里多个 ui_card 调用可能撞 surfaceId
// （固定模板按卡片类型命名，同类型第二张卡就会重复，如两张 timeline 卡）。
// MessageProcessor 的 surfacesMap 按 surfaceId 存 surface，撞 ID 时第二张卡会被
// 第一张吞掉（重复 createSurface + updateComponents 相互覆盖），界面只剩一张卡。
//
// 路由语义（每个 surfaceId 独立维护，副本之间互不覆盖）：
// - 卡实例列表：首个保留原 id，副本依次为 sid-2/sid-3...；
// - 活跃指针：createSurface 副本追加实例并把指针指向它；
// - updateComponents/updateDataModel/deleteSurface 路由到指针指向的实例
//   （真实数据里每张卡的 envelopes 连续成批出现，update 紧跟自己的 create）；
// - 若活跃实例已收到过 update/delete，回退到最早的从未更新过的实例——
//   「先集中 create 再集中 update」的模式下把内容摊到各卡，避免全挤在最后一张。
// 对没有撞 ID 的常规数据是 no-op。

export function dedupeSurfaceIds(msgs: Array<Record<string, unknown>>): void {
  const seen = new Set<string>();
  // surfaceId -> 卡实例列表（按创建顺序，instances[0] 恒为原 id）
  const instances = new Map<string, string[]>();
  // surfaceId -> 最近一次 createSurface 的实例下标
  const active = new Map<string, number>();
  // 实例 id -> 是否已收到过 update/delete（用于集中 update 模式的摊开回退）
  const touched = new Map<string, boolean>();
  const kinds = ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"];
  for (const m of msgs) {
    for (const kind of kinds) {
      const body = m?.[kind] as { surfaceId?: string } | undefined;
      if (!body || typeof body !== "object" || typeof body.surfaceId !== "string") continue;
      const sid = body.surfaceId;
      if (kind === "createSurface") {
        if (!seen.has(sid)) {
          seen.add(sid);
          instances.set(sid, [sid]);
          active.set(sid, 0);
        } else {
          // 副本编号按实例数顺推，并跳过已被显式占用的 id（防与真实 id 撞车）
          let n = (instances.get(sid)?.length ?? 1) + 1;
          while (seen.has(`${sid}-${n}`)) n++;
          const nsid = `${sid}-${n}`;
          seen.add(nsid);
          const list = instances.get(sid) ?? [sid];
          list.push(nsid);
          instances.set(sid, list);
          active.set(sid, list.length - 1);
          body.surfaceId = nsid;
        }
      } else {
        // 路由到最近一次 createSurface 的实例；从未 create 过的引用原样保留
        const list = instances.get(sid);
        const idx = active.get(sid);
        if (!list || idx === undefined) continue;
        if (kind === "deleteSurface") {
          // deleteSurface 是破坏性精确操作，直接路由到 active 指针，不参与 touched 回退
          body.surfaceId = list[idx];
        } else {
          let target = list[idx];
          if (touched.get(target)) {
            const fallback = list.find((id) => !touched.get(id));
            if (fallback !== undefined) target = fallback;
          }
          touched.set(target, true);
          body.surfaceId = target;
        }
      }
    }
  }
}
