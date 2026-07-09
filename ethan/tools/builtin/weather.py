"""Weather Tool — 基于 wttr.in，无需 API Key。"""
import urllib.parse

import httpx

from ethan.tools.base import BaseTool


class WeatherTool(BaseTool):
    fast_path = False
    name = "get_weather"
    description = (
        "Get current weather and short forecast for a city. "
        "Supports Chinese city names (北京, 上海) and English names (Beijing, Tokyo). "
        "Returns temperature, weather condition, humidity, wind, and optional multi-day forecast."
    )
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name in Chinese or English, e.g. '北京', 'Shanghai', 'Tokyo'.",
            },
            "days": {
                "type": "integer",
                "description": "Number of forecast days: 1=today only, 2=today+tomorrow, 3=3-day (default: 2).",
                "default": 2,
            },
        },
        "required": ["city"],
    }

    async def run(self, city: str, days: int = 2) -> str:
        try:
            encoded_city = urllib.parse.quote(city)
            url = f"https://wttr.in/{encoded_city}?format=j1"
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "curl/7.68.0", "Accept": "application/json"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            return self._format(data, city, days)
        except httpx.HTTPStatusError as e:
            return f"Weather query failed: HTTP {e.response.status_code}"
        except Exception as e:
            return f"Weather query failed: {e}"

    def _format(self, data: dict, city: str, days: int) -> str:
        lines: list[str] = []

        # 当前状况
        cur = data.get("current_condition", [{}])[0]
        desc = cur.get("weatherDesc", [{}])[0].get("value", "")
        temp_c = cur.get("temp_C", "?")
        feels = cur.get("FeelsLikeC", "?")
        humidity = cur.get("humidity", "?")
        wind_kmph = cur.get("windspeedKmph", "?")
        wind_dir = cur.get("winddir16Point", "")
        vis = cur.get("visibility", "?")

        lines.append(f"📍 {city} 当前天气")
        lines.append(f"  天气：{desc}")
        lines.append(f"  温度：{temp_c}°C（体感 {feels}°C）")
        lines.append(f"  湿度：{humidity}%  能见度：{vis}km")
        lines.append(f"  风：{wind_dir} {wind_kmph} km/h")

        # 预报
        weather_days = data.get("weather", [])
        day_labels = ["今天", "明天", "后天"]
        for i, w in enumerate(weather_days[:max(1, days)]):
            if i >= days:
                break
            date = w.get("date", "")
            max_c = w.get("maxtempC", "?")
            min_c = w.get("mintempC", "?")
            hourly = w.get("hourly", [])
            # 取 12 点的天气描述
            desc_day = ""
            for h in hourly:
                if h.get("time", "") in ("1200", "1100"):
                    desc_day = h.get("weatherDesc", [{}])[0].get("value", "")
                    break
            if not desc_day and hourly:
                desc_day = hourly[len(hourly) // 2].get("weatherDesc", [{}])[0].get("value", "")

            label = day_labels[i] if i < len(day_labels) else date
            lines.append(f"\n📅 {label}（{date}）：{desc_day}，{min_c}°C ~ {max_c}°C")

        return "\n".join(lines)
