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
export function formatTrigger(trigger: string): string {
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

    const dayNameMap: Record<string, string> = {
      "0": "周日", "1": "周一", "2": "周二", "3": "周三",
      "4": "周四", "5": "周五", "6": "周六", "7": "周日",
      "mon": "周一", "tue": "周二", "wed": "周三", "thu": "周四",
      "fri": "周五", "sat": "周六", "sun": "周日",
    }

    // 解析星期：支持 "mon-fri"（range）、"mon,wed,fri"（list）、"1-5"（数字 range）
    const formatDow = (d: string): string => {
      if (isWild(d)) return ""
      // range: "mon-fri" or "1-5"
      const rangeMatch = d.match(/^(\w+)-(\w+)$/)
      if (rangeMatch) {
        const fromKey = rangeMatch[1].toLowerCase()
        const toKey = rangeMatch[2].toLowerCase()
        // 覆盖整周的 range → "每天"
        const fullWeekRanges = new Set(["0-6", "0-7", "1-7", "mon-sun", "sun-sat"])
        if (fullWeekRanges.has(`${fromKey}-${toKey}`)) return "每天"
        const from = dayNameMap[fromKey] ?? rangeMatch[1]
        const to = dayNameMap[toKey] ?? rangeMatch[2]
        return `每${from}~${to}`
      }
      // comma list
      const parts = d.split(",").map(s => dayNameMap[s.trim().toLowerCase()] ?? s.trim())
      if (parts.length === 7 || (parts.length === 1 && isWild(parts[0]))) return "每天"
      return `每${parts.join("、")}`
    }

    // 解析时间部分：hour + minute 组合成可读描述
    const formatTime = (h: string, m: string): string => {
      // every N minutes via */N
      if (m.startsWith("*/")) {
        const n = m.slice(2)
        if (isWild(h)) return `每 ${n} 分钟`
        if (h.includes("-")) return `${h.replace("-", "~")} 点，每 ${n} 分钟`
        return `${h} 点，每 ${n} 分钟`
      }

      const hasHourRange = h.includes("-")
      const hasMinuteList = m.includes(",")

      // hour range + minute list: "10-22点，第10/25/40/55分钟"
      if (hasHourRange && hasMinuteList) {
        const [hFrom, hTo] = h.split("-")
        const mins = m.split(",").join("/")
        return `${hFrom}~${hTo} 点，第 ${mins} 分钟`
      }
      // hour range + single minute: "10~22点，第10分钟" or "10:10~22:10"
      if (hasHourRange && !hasMinuteList && !isWild(m)) {
        const [hFrom, hTo] = h.split("-")
        const mm = m.padStart(2, "0")
        return `${hFrom}:${mm} ~ ${hTo}:${mm}`
      }
      // hour range + wildcard minute
      if (hasHourRange && isWild(m)) {
        const [hFrom, hTo] = h.split("-")
        return `${hFrom}~${hTo} 点，每分钟`
      }
      // single/list hour + minute list
      if (!isWild(h) && hasMinuteList) {
        const mins = m.split(",").join("/")
        return `${h} 点，第 ${mins} 分钟`
      }
      // simple: single hour + single minute
      if (!isWild(h) && !isWild(m)) {
        return `${h.padStart(2, "0")}:${m.padStart(2, "0")}`
      }
      // wildcard hour + minute list
      if (isWild(h) && hasMinuteList) {
        const mins = m.split(",").join("/")
        return `每小时第 ${mins} 分钟`
      }
      if (isWild(h) && !isWild(m)) {
        return `每小时第 ${m} 分钟`
      }
      return "每分钟"
    }

    const dowStr = formatDow(dow)
    const timeStr = formatTime(hour, minute)

    // monthly
    if (!isWild(dom) && isWild(dow)) {
      return `每月 ${dom} 日 ${timeStr}`
    }

    if (dowStr) {
      return `${dowStr}，${timeStr}`
    }
    return `每天，${timeStr}`
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
