# === Tennis bot with reliable daily reminder (no APScheduler) ===
import asyncio, nest_asyncio, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

nest_asyncio.apply()

TELEGRAM_TOKEN = "8364164697:AAE0c8ANNW9o4E6Ia37yuPpj87CnY8xr79Y"
DEFAULT_TZ = "Asia/Kolkata"

# 🔔 set your reminder time here (24h format, IST)
REMINDER_HOUR = 18
REMINDER_MIN  = 41

# who will receive reminders (anyone who typed /start in this run)
subscribed_users = set()

# ---------- your working provider (unchanged) ----------
class TennisEventsProvider:
    def __init__(self):
        self.urls = {
            "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
            "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard",
        }
        self.headers = {"User-Agent": "Mozilla/5.0"}

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

                        all_tournaments.setdefault(tournament_name, set())
                        for c in competitors:
                            all_tournaments[tournament_name].add(self._safe_name(c).upper())

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
                                "score": f"{score_home}-{score_away}" if (score_home or score_away) else "TBD",
                                "status": status,
                                "time": dt,
                            })

        # tournaments that include Sinner/Djokovic/Alcaraz
        fav_players = ["SINNER", "DJOKOVIC", "DJOKOVIĆ", "ALCARAZ"]
        fav_tours = {t for t, players in all_tournaments.items() if any(p in " ".join(players) for p in fav_players)}

        today = datetime.now(ZoneInfo(DEFAULT_TZ)).date()
        return [
            m for m in all_matches
            if m["league"] in fav_tours
            and m["time"].astimezone(ZoneInfo(DEFAULT_TZ)).date() == today
        ]

PROVIDER = TennisEventsProvider()

# ---------- formatting ----------
def format_events(events):
    grouped = {}
    for ev in events:
        grouped.setdefault(ev["league"], []).append(ev)

    text = "🎾 *Today’s Matches*\n\n"
    for league, matches in grouped.items():
        text += f"🏆 *{league}*\n"
        for m in matches:
            local = m["time"].astimezone(ZoneInfo(DEFAULT_TZ))
            time_str = local.strftime("%I:%M %p").lstrip("0")
            status = m.get("status","").replace("Scheduled","").replace("Final","Completed").strip()

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
    return text.strip()

# ---------- commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    subscribed_users.add(cid)
    print("subscribed:", cid)
    await update.message.reply_text("✅ Subscribed! you’ll get the daily reminder at the set time.")

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = PROVIDER.get_events()
    if not events:
        await update.message.reply_text("😴 No matches today in those tournaments.")
        return
    await update.message.reply_text(format_events(events), parse_mode="Markdown")

# ---------- reminder logic (pure asyncio) ----------
async def send_reminder(bot):
    events = PROVIDER.get_events()
    if not events:
        print("no matches today → skip reminder")
        return
    msg = format_events(events)
    for cid in list(subscribed_users):
        try:
            await bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
            print("sent to", cid)
        except Exception as e:
            print("send error", cid, e)

def seconds_until(hour:int, minute:int, tz:str) -> float:
    now = datetime.now(ZoneInfo(tz))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()

async def daily_scheduler(bot, hour:int, minute:int, tz:str):
    while True:
        secs = seconds_until(hour, minute, tz)
        print(f"⏳ sleeping {int(secs)}s until next reminder ({hour:02d}:{minute:02d} {tz})")
        await asyncio.sleep(secs)
        try:
            await send_reminder(bot)
        except Exception as e:
            print("reminder error:", e)
        # tiny buffer to avoid duplicate triggers if clock slip
        await asyncio.sleep(2)

# ---------- main ----------
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))

    # start the daily scheduler in the background
    asyncio.create_task(daily_scheduler(app.bot, REMINDER_HOUR, REMINDER_MIN, DEFAULT_TZ))

    print(f"🎾 Tennis Bot is live — daily reminder at {REMINDER_HOUR:02d}:{REMINDER_MIN:02d} {DEFAULT_TZ}.")
    await app.run_polling()

asyncio.get_event_loop().run_until_complete(main())

