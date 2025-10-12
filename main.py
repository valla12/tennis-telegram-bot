import asyncio, nest_asyncio, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

nest_asyncio.apply()

# ---- CONFIG ----
TELEGRAM_TOKEN = "8364164697:AAE0c8ANNW9o4E6Ia37yuPpj87CnY8xr79Y"
DEFAULT_TZ = "Asia/Kolkata"

# ---- DATA PROVIDER ----
class TennisEventsProvider:
    def __init__(self):
        self.urls = {
            "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
            "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard",
        }
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }

    def _safe_name(self, c):
        return (
            c.get("athlete", {}).get("displayName")
            or c.get("displayName")
            or c.get("team", {}).get("displayName")
            or "TBD"
        )

    def get_events(self):
        all_matches = []
        all_tournaments = {}

        # 🎾 Step 1: fetch everything
        for tour, url in self.urls.items():
            try:
                data = requests.get(url, headers=self.headers, timeout=10).json()
            except Exception as e:
                print(f"[{tour}] error:", e)
                continue

            for ev in data.get("events", []):
                tournament_name = ev.get("name") or ev.get("shortName") or tour

                for grp in ev.get("groupings", []):
                    for comp in grp.get("competitions", []):
                        competitors = comp.get("competitors", [])
                        notes = comp.get("notes", [])

                        # store all players seen in this tournament
                        if tournament_name not in all_tournaments:
                            all_tournaments[tournament_name] = set()

                        for c in competitors:
                            all_tournaments[tournament_name].add(
                                self._safe_name(c).upper()
                            )

                        # normal match or completed match
                        date_str = comp.get("date") or ev.get("date", "")
                        try:
                            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        except Exception:
                            dt = datetime.now(ZoneInfo("UTC"))

                        if notes:
                            summary = notes[0].get("text", "")
                            all_matches.append({
                                "league": tournament_name,
                                "home": summary,
                                "away": "",
                                "status": comp.get("status", {}).get("type", {}).get("description", ""),
                                "time": dt,
                            })
                        elif len(competitors) >= 2:
                            home = self._safe_name(competitors[0])
                            away = self._safe_name(competitors[1])
                            score_home = competitors[0].get("score", "")
                            score_away = competitors[1].get("score", "")
                            status = comp.get("status", {}).get("type", {}).get("description", "")
                            all_matches.append({
                                "league": tournament_name,
                                "home": home,
                                "away": away,
                                "score": f"{score_home}-{score_away}" if score_home or score_away else "TBD",
                                "status": status,
                                "time": dt,
                            })

        # 🎾 Step 2: detect tournaments that include Sinner / Djokovic / Alcaraz
        fav_players = ["SINNER", "DJOKOVIC", "DJOKOVIĆ", "ALCARAZ"]
        fav_tournaments = set()
        for tname, players in all_tournaments.items():
            if any(p in " ".join(players) for p in fav_players):
                fav_tournaments.add(tname)

        print("🎯 Fav tournaments detected:", fav_tournaments)

        # 🎾 Step 3: filter today's matches only (from those tournaments)
        now_local = datetime.now(ZoneInfo(DEFAULT_TZ))
        today_date = now_local.date()

        filtered = [
            m for m in all_matches
            if m["league"] in fav_tournaments
            and m["time"].astimezone(ZoneInfo(DEFAULT_TZ)).date() == today_date
        ]

        print(f"✅ Parsed {len(filtered)} matches in fav tournaments for today")
        for m in filtered[:5]:
            print(f"→ {m['league']}: {m['home']} vs {m.get('away','')} ({m['status']})")

        return filtered


PROVIDER = TennisEventsProvider()

# ---- BOT ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎾 Hey! I’ll show today's matches in tournaments where Sinner, Djokovic, or Alcaraz are playing.\n\n"
        "Use /today to get the list."
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = PROVIDER.get_events()
    if not events:
        await update.message.reply_text("😴 No matches today in those tournaments.")
        return

    # group matches by tournament
    grouped = {}
    for ev in events:
        grouped.setdefault(ev["league"], []).append(ev)

    # 🎨 format text nicely
    text = "🎾 *Today’s Matches*\n\n"
    for league, matches in grouped.items():
        text += f"🏆 *{league}*\n"
        for m in matches:
            local = m["time"].astimezone(ZoneInfo(DEFAULT_TZ))
            time_str = local.strftime("%I:%M %p").lstrip("0")  # 09:00 → 9:00
            status = m["status"].replace("Scheduled", "").replace("Final", "Completed").strip()

            if m.get("away"):
                line = f"   {m['home']} vs {m['away']}"
                if m.get('score') and m['score'] != 'TBD':
                    line += f"  [{m['score']}]"
            else:
                line = f"   {m['home']}"

            if status:
                line += f" — {status}"
            line += f"  ({time_str})"

            text += line + "\n"
        text += "\n"

    # send in chunks (telegram 4096 limit)
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], parse_mode="Markdown")

# ---- MAIN ----
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    print("🎾 Tennis Bot is live! Type /start in Telegram.")
    await app.run_polling()

asyncio.get_event_loop().run_until_complete(main())
