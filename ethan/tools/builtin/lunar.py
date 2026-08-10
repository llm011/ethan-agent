"""Lunar Calendar Tool — 公历农历互转，支持干支、生肖、节气、节日。"""
from datetime import date

from lunar_python import Lunar, Solar

from ethan.tools.base import BaseTool


class LunarCalendarTool(BaseTool):
    fast_path = True
    name = "lunar_calendar"
    description = (
        "Convert between solar (Gregorian) and lunar (Chinese traditional) calendar. "
        "Supports solar-to-lunar, lunar-to-solar conversion, and querying today's lunar info "
        "with Ganzhi (干支), zodiac animal (生肖), solar terms (节气), and festivals (节日). "
        "Use this when user asks about Chinese lunar dates, lunar birthdays, traditional holidays, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action to perform: 'today' (get today's lunar info, default), 'solar2lunar' (solar to lunar), 'lunar2solar' (lunar to solar).",
                "enum": ["today", "solar2lunar", "lunar2solar"],
                "default": "today",
            },
            "year": {
                "type": "integer",
                "description": "Year (solar year for solar2lunar, lunar year for lunar2solar). Not required for 'today' action.",
            },
            "month": {
                "type": "integer",
                "description": "Month (1-12 for solar, 1-12 for lunar; use negative for leap month, e.g. -6 = 闰六月).",
            },
            "day": {
                "type": "integer",
                "description": "Day of month.",
            },
        },
        "required": [],
    }

    async def run(self, action: str = "today", year: int | None = None, month: int | None = None, day: int | None = None) -> str:
        try:
            if action == "today":
                return self._today()
            elif action == "solar2lunar":
                if year is None or month is None or day is None:
                    return "Error: year, month, day are required for solar2lunar action."
                return self._solar_to_lunar(year, month, day)
            elif action == "lunar2solar":
                if year is None or month is None or day is None:
                    return "Error: year, month, day are required for lunar2solar action. Use negative month for leap month (e.g. month=-6 for 闰六月)."
                return self._lunar_to_solar(year, month, day)
            else:
                return f"Error: unknown action '{action}'. Use 'today', 'solar2lunar', or 'lunar2solar'."
        except Exception as e:
            return f"Lunar calendar error: {e}"

    def _today(self) -> str:
        today = date.today()
        solar = Solar.fromYmd(today.year, today.month, today.day)
        lunar = solar.getLunar()
        return self._format_detail(solar, lunar)

    def _solar_to_lunar(self, year: int, month: int, day: int) -> str:
        solar = Solar.fromYmd(year, month, day)
        lunar = solar.getLunar()
        return self._format_detail(solar, lunar)

    def _lunar_to_solar(self, year: int, month: int, day: int) -> str:
        lunar = Lunar.fromYmd(year, month, day)
        solar = lunar.getSolar()
        return self._format_detail(solar, lunar)

    def _format_detail(self, solar: Solar, lunar: Lunar) -> str:
        lines: list[str] = []

        # 日期
        lines.append(f"📅 公历：{solar.getYear()}年{solar.getMonth()}月{solar.getDay()}日 星期{solar.getWeekInChinese()}")
        lines.append(f"🌙 农历：{lunar}")

        # 干支和生肖
        lines.append(f"   干支：{lunar.getYearInGanZhi()}年 {lunar.getMonthInGanZhi()}月 {lunar.getDayInGanZhi()}日")
        lines.append(f"   生肖：{lunar.getYearShengXiao()}年")

        # 节气
        jieqi = lunar.getJieQi()
        if jieqi:
            lines.append(f"   节气：{jieqi}")

        # 节日
        festivals = []
        try:
            festivals.extend(solar.getFestivals())
        except Exception:
            pass
        try:
            festivals.extend(lunar.getFestivals())
        except Exception:
            pass
        try:
            festivals.extend(lunar.getOtherFestivals())
        except Exception:
            pass
        if festivals:
            lines.append(f"   节日：{'、'.join(festivals)}")

        # 八字（可选）
        try:
            bazi = lunar.getEightChar()
            lines.append(f"   八字：{bazi}")
        except Exception:
            pass

        return "\n".join(lines)
