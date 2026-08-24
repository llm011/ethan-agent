// A2UI envelope 的 surfaceId 去重：同一条消息里多个 ui_card 调用可能撞 surfaceId
// （固定模板按卡片类型命名，同类型第二张卡就会重复，如两张 timeline 卡）。
// MessageProcessor 的 surfacesMap 按 surfaceId 存 surface，撞 ID 时第二张卡会被
// 第一张吞掉（重复 createSurface + updateComponents 相互覆盖），界面只剩一张卡。
// 这里按顺序扫描 envelopes：重复的 createSurface 改成唯一 ID（sid-2/sid-3...），
// 其后的 updateComponents/updateDataModel/deleteSurface 引用一并跟着改，
// 保证每张卡都落在一个独立 surface 上。对没有撞 ID 的常规数据是 no-op。

export function dedupeSurfaceIds(msgs: Array<Record<string, unknown>>): void {
  const seen = new Set<string>();
  const remap = new Map<string, string>();
  const kinds = ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"];
  for (const m of msgs) {
    for (const kind of kinds) {
      const body = m?.[kind] as { surfaceId?: string } | undefined;
      if (!body || typeof body !== "object" || typeof body.surfaceId !== "string") continue;
      const sid = body.surfaceId;
      if (kind === "createSurface") {
        if (!seen.has(sid)) {
          seen.add(sid);
        } else {
          let n = 2;
          while (seen.has(`${sid}-${n}`)) n++;
          const nsid = `${sid}-${n}`;
          seen.add(nsid);
          remap.set(sid, nsid);
          body.surfaceId = nsid;
        }
      } else if (remap.has(sid)) {
        body.surfaceId = remap.get(sid) as string;
      }
    }
  }
}
