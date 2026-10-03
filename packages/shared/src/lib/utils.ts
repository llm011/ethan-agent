import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// token 数紧凑显示：890379 → "890k"，1500000 → "1.5M"。按十进制 /1000（token 是计数，非字节）。
export function fmtTokens(n: number | undefined | null): string {
  const v = Number(n || 0)
  if (v >= 1_000_000) {
    const m = Math.floor(v / 10000) / 100  // floor 到百分位，避免 999999 → "1.0M"
    return `${m.toFixed(1).replace(/\.0$/, "")}M`
  }
  if (v >= 10_000) return `${Math.floor(v / 1000)}k`
  if (v >= 1000) return `${(Math.floor(v / 100) / 10).toFixed(1)}k`
  return String(v)
}

// "interval[0:10:00]" → "每 10 分钟"
// "cron[minute='0', hour='9', ...]" → "每天 09:00"
// "cron[hour='*', minute='17']" → "每小时第 17 分"
export function formatTrigger(trigger: string): string {
  // date[2026-10-15 14:30:00+08:00]
  const dateMatch = trigger.match(/date\[(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})/)
  if (dateMatch) {
    return `单次 ${dateMatch[1]} ${dateMatch[2]}`
  }

  // interval[H:MM:SS]
  const intervalMatch = trigger.match(/interval\[(\d+):(\d+):(\d+)\]/)
  if (intervalMatch) {
    const h = parseInt(intervalMatch[1])
    const m = parseInt(intervalMatch[2])
    const s = parseInt(intervalMatch[3])
    const total = h * 3600 + m * 60 + s
    if (total < 60) return `每 ${total} 秒`
    if (total < 3600) {
      const mins = Math.round(total / 60)
      return `每 ${mins} 分钟`
    }
    if (total < 86400) {
      const hours = total / 3600
      return Number.isInteger(hours) ? `每 ${hours} 小时` : `每 ${(total / 3600).toFixed(1)} 小时`
    }
    const days = Math.round(total / 86400)
    return `每 ${days} 天`
  }

  // cron[key='val', ...]
  const cronMatch = trigger.match(/cron\[(.+)\]/)
  if (cronMatch) {
    const p: Record<string, string> = {}
    for (const m of cronMatch[1].matchAll(/(\w+)='([^']+)'/g)) {
      p[m[1]] = m[2]
    }
    const isWild = (v: string | undefined) => !v || v === "*"
    const minute = p.minute ?? "*"
    const hour = p.hour ?? "*"
    const dow = p.day_of_week ?? "*"
    const dom = p.day ?? "*"
    const month = p.month ?? "*"

    const dayNames: Record<string, string> = {
      "0": "周日", "1": "周一", "2": "周二", "3": "周三",
      "4": "周四", "5": "周五", "6": "周六", "7": "周日",
      "mon": "周一", "tue": "周二", "wed": "周三", "thu": "周四",
      "fri": "周五", "sat": "周六", "sun": "周日",
    }

    const pad2 = (v: string) => v.length >= 2 ? v : "0" + v
    const padTime = (h: string, m: string) => {
      const hh = isWild(h) ? "?" : pad2(h)
      const mm = isWild(m) ? "00" : pad2(m)
      return `${hh}:${mm}`
    }
    // 小时字段可能是多值（`9,21`）：展开成「09:00、21:00」
    const fmtHours = (h: string, m: string) =>
      h.includes(",")
        ? h.split(",").map(x => padTime(x.trim(), m)).join("、")
        : padTime(h, m)

    const formatDow = (d: string) => {
      const lower = d.trim().toLowerCase()
      if (isWild(lower)) return ""
      if (lower === "mon-fri" || lower === "1-5") return "工作日"
      if (["sat,sun", "sun,sat", "6,0", "0,6", "6,7", "7,6"].includes(lower)) return "周末"
      return lower.split(",").map(x => dayNames[x.trim()] ?? x.trim()).join("、")
    }

    const formatMinutes = (min: string) => {
      if (min.startsWith("*/")) return `每 ${min.slice(2)} 分钟`
      if (min.includes(",")) return `${min.split(",").map(x => pad2(x.trim())).join("、")} 分`
      if (isWild(min) || min === "0") return "整点"
      return `第 ${pad2(min)} 分`
    }

    const dowStr = formatDow(dow)
    const dowPrefix = !dowStr ? "" : ["工作日", "周末"].includes(dowStr) ? `${dowStr} ` : `每 ${dowStr} `

    // 1. 每 N 分钟
    if (minute.startsWith("*/")) {
      const step = minute.slice(2)
      if (isWild(hour)) return `${dowPrefix}每 ${step} 分钟`
      if (hour.includes("-")) return `${dowPrefix}${hour} 点每 ${step} 分钟`
      return `${dowPrefix}${fmtHours(hour, "00")} 起每 ${step} 分钟`
    }

    // 2. 每小时（hour 通配符，如 hour='*'）
    if (isWild(hour)) {
      const minStr = formatMinutes(minute)
      const joiner = /^\d/.test(minStr) ? " " : ""
      return `${dowPrefix}每小时${joiner}${minStr}`
    }

    // 3. 小时范围（如 hour='9-18' 或 '10-23'）
    if (hour.includes("-")) {
      const minStr = isWild(minute) || minute === "0" ? "整点" : `:${pad2(minute)}`
      return `${dowPrefix || "每天 "}${hour} 点 ${minStr}`
    }

    // 4. 每年固定月份+日期
    if (!isWild(month) && !isWild(dom)) {
      return `每年 ${month}月${dom}日 ${fmtHours(hour, minute)}`
    }

    // 5. 每年固定月份
    if (!isWild(month)) {
      return `每年 ${month}月 ${fmtHours(hour, minute)}`
    }

    // 6. 每月固定日
    if (!isWild(dom) && isWild(dow)) {
      return `每月 ${dom} 日 ${fmtHours(hour, minute)}`
    }

    // 7. 指定星期几 / 工作日 / 周末
    if (!isWild(dow) && isWild(dom)) {
      return `${dowPrefix}${fmtHours(hour, minute)}`
    }

    // 8. 每天固定时间
    if (!isWild(hour) && isWild(dow) && isWild(dom)) {
      return `每天 ${fmtHours(hour, minute)}`
    }

    // 9. 兜底格式化：把非通配字段拼接起来，绝不输出带 * 的机器字符串
    const parts: string[] = []
    if (!isWild(month)) parts.push(`${month}月`)
    if (!isWild(dom)) parts.push(`${dom}日`)
    if (dowPrefix.trim()) parts.push(dowPrefix.trim())
    if (!isWild(hour) || !isWild(minute)) parts.push(fmtHours(hour, minute))
    if (parts.length > 0) return parts.join(" ")
  }

  return trigger
}

// "2026-06-15 00:21:35+08:00" → "3 分钟后（00:24）"
export function formatNextRun(nextRunTime: string | null | undefined): string {
  if (!nextRunTime) return "已暂停"
  const next = new Date(nextRunTime)
  if (isNaN(next.getTime())) return nextRunTime
  const now = new Date()
  const diffMs = next.getTime() - now.getTime()
  const diffMins = Math.round(diffMs / 60000)
  const timeStr = next.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })

  if (diffMins < 0) return `已过期（${timeStr}）`
  if (diffMins < 1) return `即将执行（${timeStr}）`
  if (diffMins < 60) return `${diffMins} 分钟后（${timeStr}）`
  if (diffMins < 1440) {
    const h = Math.floor(diffMins / 60)
    const m = diffMins % 60
    const suffix = m > 0 ? `${h} 小时 ${m} 分钟后` : `${h} 小时后`
    return `${suffix}（${timeStr}）`
  }
  const dateStr = next.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })
  return `${dateStr} ${timeStr}`
}
