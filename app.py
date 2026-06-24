from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import json
import os
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = "wc-predictions-2026"

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
ADMIN_PASSWORD = "miac2026"

# Country flag emojis
FLAGS = {
    "Mexico": "🇲🇽", "South Africa": "🇿🇦", "South Korea": "🇰🇷", "Czech Republic": "🇨🇿",
    "Canada": "🇨🇦", "Bosnia & Herzegovina": "🇧🇦", "USA": "🇺🇸", "Paraguay": "🇵🇾",
    "Qatar": "🇶🇦", "Switzerland": "🇨🇭", "Brazil": "🇧🇷", "Morocco": "🇲🇦",
    "Haiti": "🇭🇹", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Australia": "🇦🇺", "Turkey": "🇹🇷",
    "Germany": "🇩🇪", "Curacao": "🇨🇼", "Ivory Coast": "🇨🇮", "Ecuador": "🇪🇨",
    "Netherlands": "🇳🇱", "Japan": "🇯🇵", "Sweden": "🇸🇪", "Tunisia": "🇹🇳",
    "Belgium": "🇧🇪", "Egypt": "🇪🇬", "Iran": "🇮🇷", "New Zealand": "🇳🇿",
    "Spain": "🇪🇸", "Cape Verde": "🇨🇻", "Saudi Arabia": "🇸🇦", "Uruguay": "🇺🇾",
    "France": "🇫🇷", "Senegal": "🇸🇳", "Iraq": "🇮🇶", "Norway": "🇳🇴",
    "Argentina": "🇦🇷", "Algeria": "🇩🇿", "Austria": "🇦🇹", "Jordan": "🇯🇴",
    "Portugal": "🇵🇹", "DR Congo": "🇨🇩", "Uzbekistan": "🇺🇿", "Colombia": "🇨🇴",
    "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Croatia": "🇭🇷", "Ghana": "🇬🇭", "Panama": "🇵🇦",
}

app.jinja_env.globals.update(get_flag=lambda team: FLAGS.get(team, "🏳️"))

def format_time_12h(time_str):
    """Convert 24h time (00:30) to 12h format (12:30 AM)"""
    try:
        hour, minute = map(int, time_str.split(":"))
        if hour == 0:
            return f"12:{minute:02d} AM"
        elif hour < 12:
            return f"{hour}:{minute:02d} AM"
        elif hour == 12:
            return f"12:{minute:02d} PM"
        else:
            return f"{hour-12}:{minute:02d} PM"
    except:
        return time_str

app.jinja_env.globals.update(format_time=format_time_12h)


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            team_a TEXT NOT NULL,
            team_b TEXT NOT NULL,
            date TEXT NOT NULL,
            kickoff TEXT DEFAULT '',
            result_winner TEXT DEFAULT '',
            result_scorer TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            name TEXT PRIMARY KEY,
            pin TEXT DEFAULT ''
        )
    """)
    # Add pin column if not exists (for existing databases)
    cur.execute("""
        DO $$
        BEGIN
            ALTER TABLE players ADD COLUMN pin TEXT DEFAULT '';
        EXCEPTION WHEN duplicate_column THEN
            NULL;
        END $$;
    """)
    # Add fav_team column if not exists
    cur.execute("""
        DO $$
        BEGIN
            ALTER TABLE players ADD COLUMN fav_team TEXT DEFAULT '';
        EXCEPTION WHEN duplicate_column THEN
            NULL;
        END $$;
    """)
    # Add nickname column if not exists
    cur.execute("""
        DO $$
        BEGIN
            ALTER TABLE players ADD COLUMN nickname TEXT DEFAULT '';
        EXCEPTION WHEN duplicate_column THEN
            NULL;
        END $$;
    """)
    conn.commit()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            player TEXT NOT NULL,
            match_id TEXT NOT NULL,
            winner TEXT DEFAULT '',
            scorer TEXT DEFAULT '',
            PRIMARY KEY (player, match_id)
        )
    """)
    # Announcements table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            active BOOLEAN DEFAULT TRUE
        )
    """)
    conn.commit()
    # Add kickoff column if not exists (for existing databases)
    try:
        cur.execute("ALTER TABLE matches ADD COLUMN kickoff TEXT DEFAULT ''")
        conn.commit()
    except:
        conn.rollback()
    conn.close()


def load_matches():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM matches ORDER BY sort_order, id")
    matches = cur.fetchall()
    conn.close()
    return [dict(m) for m in matches]


def load_players():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM players ORDER BY name")
    players = [row[0] for row in cur.fetchall()]
    conn.close()
    return players


def load_player_teams():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, fav_team FROM players")
    teams = {row[0]: row[1] for row in cur.fetchall() if row[1]}
    conn.close()
    return teams


def load_predictions():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM predictions")
    rows = cur.fetchall()
    conn.close()
    preds = {}
    for row in rows:
        if row["player"] not in preds:
            preds[row["player"]] = {}
        preds[row["player"]][row["match_id"]] = {
            "winner": row["winner"],
            "scorer": row["scorer"],
        }
    return preds


def load_announcements():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM announcements WHERE active = TRUE ORDER BY created_at DESC LIMIT 3")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def seed_matches():
    """Seed initial matches if table is empty."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM matches")
    count = cur.fetchone()[0]
    if count == 0:
        # Times are in IST (UTC+5:30)
        matches = [
            ("match_1", "Mexico", "South Africa", "June 11", "00:30", 1),
            ("match_2", "South Korea", "Czech Republic", "June 12", "07:30", 2),
            ("match_3", "Canada", "Bosnia & Herzegovina", "June 13", "00:30", 3),
            ("match_4", "USA", "Paraguay", "June 13", "06:30", 4),
            ("match_5", "Qatar", "Switzerland", "June 14", "00:30", 5),
            ("match_6", "Brazil", "Morocco", "June 14", "03:30", 6),
            ("match_7", "Haiti", "Scotland", "June 14", "06:30", 7),
            ("match_8", "Australia", "Turkey", "June 14", "09:30", 8),
            ("match_9", "Germany", "Curacao", "June 14", "22:30", 9),
            ("match_10", "Ivory Coast", "Ecuador", "June 15", "02:30", 10),
            ("match_11", "Netherlands", "Japan", "June 15", "01:30", 11),
            ("match_12", "Sweden", "Tunisia", "June 15", "07:30", 12),
            ("match_13", "Spain", "Cape Verde", "June 15", "21:30", 13),
            ("match_14", "Belgium", "Egypt", "June 16", "00:30", 14),
            ("match_15", "Saudi Arabia", "Uruguay", "June 16", "03:30", 15),
            ("match_16", "Iran", "New Zealand", "June 16", "06:30", 16),
            ("match_17", "France", "Senegal", "June 17", "00:30", 17),
            ("match_18", "Iraq", "Norway", "June 17", "03:30", 18),
            ("match_19", "Argentina", "Algeria", "June 17", "06:30", 19),
            ("match_20", "Austria", "Jordan", "June 17", "09:30", 20),
            ("match_21", "Portugal", "DR Congo", "June 17", "22:30", 21),
            ("match_22", "Uzbekistan", "Colombia", "June 18", "07:30", 22),
            ("match_23", "England", "Croatia", "June 18", "01:30", 23),
            ("match_24", "Ghana", "Panama", "June 18", "04:30", 24),
            ("match_25", "Czech Republic", "South Africa", "June 18", "21:30", 25),
            ("match_26", "Mexico", "South Korea", "June 19", "06:30", 26),
            ("match_27", "Switzerland", "Bosnia & Herzegovina", "June 19", "00:30", 27),
            ("match_28", "Canada", "Qatar", "June 19", "03:30", 28),
            ("match_29", "Scotland", "Morocco", "June 20", "03:30", 29),
            ("match_30", "Brazil", "Haiti", "June 20", "06:00", 30),
            ("match_31", "USA", "Australia", "June 20", "00:30", 31),
            ("match_32", "Turkey", "Paraguay", "June 20", "08:30", 32),
            ("match_33", "Germany", "Ivory Coast", "June 20", "23:30", 33),
            ("match_34", "Ecuador", "Curacao", "June 21", "05:30", 34),
            ("match_35", "Netherlands", "Sweden", "June 20", "22:30", 35),
            ("match_36", "Tunisia", "Japan", "June 21", "09:30", 36),
            ("match_37", "Belgium", "Iran", "June 22", "00:30", 37),
            ("match_38", "New Zealand", "Egypt", "June 22", "06:30", 38),
            ("match_39", "Spain", "Saudi Arabia", "June 21", "21:30", 39),
            ("match_40", "Uruguay", "Cape Verde", "June 22", "03:30", 40),
            ("match_41", "France", "Iraq", "June 23", "02:30", 41),
            ("match_42", "Norway", "Senegal", "June 23", "05:30", 42),
            ("match_43", "Argentina", "Austria", "June 22", "22:30", 43),
            ("match_44", "Jordan", "Algeria", "June 23", "08:30", 44),
            ("match_45", "Portugal", "Uzbekistan", "June 23", "22:30", 45),
            ("match_46", "Colombia", "DR Congo", "June 24", "07:30", 46),
            ("match_47", "England", "Ghana", "June 24", "01:30", 47),
            ("match_48", "Panama", "Croatia", "June 24", "04:30", 48),
        ]
        for m in matches:
            cur.execute(
                "INSERT INTO matches (id, team_a, team_b, date, kickoff, sort_order) VALUES (%s, %s, %s, %s, %s, %s)",
                m,
            )
        conn.commit()
    conn.close()


def fuzzy_match(a, b):
    if not a or not b:
        return False
    a = a.strip().lower().replace("é", "e").replace("ö", "o").replace("ü", "u").replace("ñ", "n")
    b = b.strip().lower().replace("é", "e").replace("ö", "o").replace("ü", "u").replace("ñ", "n")
    if a == b:
        return True
    if a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() > 0.75


def calculate_leaderboard():
    matches = load_matches()
    players = load_players()
    predictions = load_predictions()
    scores = {player: 0 for player in players}
    today_scores = {player: 0 for player in players}
    prev_scores = {player: 0 for player in players}
    now_ist = datetime.now(IST)
    # Session boundary: 6 PM to 6 PM
    # 6 PM to 11:59 PM (hour >= 18): current session = today evening + tomorrow morning
    # 12 AM to 5:59 PM (hour < 18): current session = yesterday evening + today morning
    # "Previous session" is the one before that (for fallback display during 6 AM-6 PM daytime)
    if now_ist.hour >= 18:
        # Evening: session just started tonight
        session_dates_current = [f"June {now_ist.day}", f"June {now_ist.day + 1}"]
        session_dates_prev = [f"June {now_ist.day - 1}", f"June {now_ist.day}"]
    else:
        # After midnight / daytime: still in last night's session
        session_dates_current = [f"June {now_ist.day - 1}", f"June {now_ist.day}"]
        session_dates_prev = [f"June {now_ist.day - 2}", f"June {now_ist.day - 1}"]
    for match in matches:
        if not match.get("result_winner"):
            continue
        for player in players:
            pred = predictions.get(player, {}).get(match["id"])
            if not pred:
                continue
            points = 0
            # Winner check
            if pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower():
                points += 1
            # Score check
            if pred.get("scorer", "").strip() == match.get("result_scorer", "").strip():
                points += 1
            # Both correct = 3 points
            if points == 2:
                points = 3
            scores[player] = scores.get(player, 0) + points
            if match.get("date") in session_dates_current:
                try:
                    hour = int(match.get("kickoff", "0").split(":")[0])
                    match_date = match.get("date", "")
                    if now_ist.hour >= 18:
                        # Tonight's session: today evening (>=18) + tomorrow morning (<10)
                        if (match_date == f"June {now_ist.day}" and hour >= 18) or (match_date == f"June {now_ist.day + 1}" and hour < 10):
                            today_scores[player] = today_scores.get(player, 0) + points
                    else:
                        # After midnight: last night's session = yesterday evening (>=18) + today morning (<10)
                        if (match_date == f"June {now_ist.day - 1}" and hour >= 18) or (match_date == f"June {now_ist.day}" and hour < 10):
                            today_scores[player] = today_scores.get(player, 0) + points
                except:
                    pass
            # Previous session
            if match.get("date") in session_dates_prev:
                try:
                    hour = int(match.get("kickoff", "0").split(":")[0])
                    match_date = match.get("date", "")
                    if now_ist.hour >= 18:
                        if (match_date == f"June {now_ist.day - 1}" and hour >= 18) or (match_date == f"June {now_ist.day}" and hour < 10):
                            prev_scores[player] = prev_scores.get(player, 0) + points
                    else:
                        if (match_date == f"June {now_ist.day - 2}" and hour >= 18) or (match_date == f"June {now_ist.day - 1}" and hour < 10):
                            prev_scores[player] = prev_scores.get(player, 0) + points
                except:
                    pass
    # Display logic:
    # 6 PM - 6 AM: active session, show current session king (today_scores)
    # 6 AM - 6 PM: daytime, show the session that just ended (today_scores = last night)
    # In both cases we show today_scores. prev_scores is only used as fallback if today has 0.
    final_today = today_scores
    return sorted(scores.items(), key=lambda x: x[-1], reverse=True), final_today


def get_today_matches():
    """Show matches for tonight's session.
    Includes today's evening matches + tomorrow's early morning matches (before 10 AM).
    """
    now_ist = datetime.now(IST)
    matches = load_matches()
    
    if now_ist.hour < 10:
        # Before 10 AM: show yesterday evening + today early morning
        today_date = f"June {now_ist.day - 1}"
        tomorrow_date = f"June {now_ist.day}"
    else:
        # After 10 AM: show today evening + tomorrow early morning
        today_date = f"June {now_ist.day}"
        tomorrow_date = f"June {now_ist.day + 1}"
    
    result = []
    for m in matches:
        if m.get("result_winner"):
            continue
        if not m.get("kickoff"):
            continue
        
        try:
            hour = int(m["kickoff"].split(":")[0])
        except:
            continue
        
        # Include: today's date with evening kickoff (>= 18:00)
        # + tomorrow's date with early morning kickoff (< 10:00)
        if m.get("date") == today_date and hour >= 18:
            result.append(m)
        elif m.get("date") == tomorrow_date and hour < 10:
            result.append(m)
    
    # Sort by kickoff time (evening first, then morning)
    def sort_key(m):
        h = int(m["kickoff"].split(":")[0])
        # Evening matches (18-23) should come before morning (0-9)
        return h if h >= 18 else h + 24
    result.sort(key=sort_key)
    
    # Mark locked matches
    for m in result:
        m["locked"] = is_match_locked(m)
    
    return result


def is_match_locked(match):
    """Check if a match has kicked off (predictions locked)."""
    if not match.get("kickoff"):
        return False
    now_ist = datetime.now(IST)
    try:
        # Parse kickoff time (HH:MM) for match date
        day = int(match["date"].replace("June ", ""))
        hour, minute = map(int, match["kickoff"].split(":"))
        kickoff_time = datetime(2026, 6, day, hour, minute, tzinfo=IST)
        return now_ist >= kickoff_time
    except:
        return False


def get_completed_matches():
    matches = load_matches()
    return [m for m in matches if m.get("result_winner")]


def get_flag(team):
    return FLAGS.get(team, "🏳️")


@app.route("/")
def home():
    try:
        now_ist = datetime.now(IST)
        leaderboard, today_scores = calculate_leaderboard()
        today_matches = get_today_matches()
        # Show all today's matches (including locked ones) on home page
        upcoming_matches = [m for m in today_matches if not m.get("locked")]
        locked_matches = [m for m in today_matches if m.get("locked")]
        completed = get_completed_matches()[-5:]
        players = load_players()
        player_teams = load_player_teams()
        predictions = load_predictions()
        all_predictions = {}
        for match in today_matches:
            all_predictions[match["id"]] = {}
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if pred:
                    all_predictions[match["id"]][player] = pred

        # Match day recap: who scored points in recent completed matches
        recap = []
        for match in completed:
            scorers = []
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if not pred:
                    continue
                points = 0
                if pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower():
                    points += 1
                if pred.get("scorer", "").strip() == match.get("result_scorer", "").strip():
                    points += 1
                if points == 2:
                    points = 3
                if points > 0:
                    scorers.append({"name": player, "points": points})
            scorers.sort(key=lambda x: x["points"], reverse=True)
            recap.append({"match": match, "scorers": scorers})

        # Calculate ranks (sequential: 1st, 2nd, 3rd regardless of ties)
        ranked_leaderboard = []
        prev_points = None
        rank = 0
        for i, (player, points) in enumerate(leaderboard):
            if points != prev_points:
                rank += 1
                prev_points = points
            ranked_leaderboard.append((player, points, rank))

        # Calculate rank changes (compare current rank vs rank without today's session points)
        prev_leaderboard = sorted(
            [(player, pts - today_scores.get(player, 0)) for player, pts in leaderboard],
            key=lambda x: x[1], reverse=True
        )
        prev_ranks = {}
        prev_rank = 0
        prev_pts_val = None
        for i, (player, pts) in enumerate(prev_leaderboard):
            if pts != prev_pts_val:
                prev_rank += 1
                prev_pts_val = pts
            prev_ranks[player] = prev_rank

        # Add rank change to leaderboard: (player, points, rank, rank_change)
        ranked_leaderboard_with_change = []
        for player, points, rank in ranked_leaderboard:
            old_rank = prev_ranks.get(player, rank)
            change = old_rank - rank  # positive = moved up, negative = moved down
            ranked_leaderboard_with_change.append((player, points, rank, change))

        # Count how many players predicted today
        today_predictors = set()
        for match in today_matches + locked_matches:
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if pred:
                    today_predictors.add(player)

        # Count yesterday's predictors for comparison
        yesterday_predictors = set()
        all_matches = load_matches()
        if now_ist.hour < 10:
            prev_today = f"June {now_ist.day - 2}"
            prev_tomorrow = f"June {now_ist.day - 1}"
        else:
            prev_today = f"June {now_ist.day - 1}"
            prev_tomorrow = f"June {now_ist.day}"
        for m in all_matches:
            if not m.get("kickoff"):
                continue
            try:
                hour = int(m["kickoff"].split(":")[0])
                if (m.get("date") == prev_today and hour >= 18) or (m.get("date") == prev_tomorrow and hour < 10):
                    for player in players:
                        pred = predictions.get(player, {}).get(m["id"])
                        if pred:
                            yesterday_predictors.add(player)
            except:
                pass

        # Find today's prediction king (minimum 3 points required)
        prediction_king = None
        if today_scores:
            max_pts = max(today_scores.values())
            if max_pts >= 3:
                kings = [p for p, pts in today_scores.items() if pts == max_pts]
                prediction_king = {"names": kings, "points": max_pts}

        # --- Record Alert: best single-session score ever ---
        # Calculate all historical session scores to find the record
        record_alert = None
        all_session_scores = {}  # {session_label: {player: points}}
        for match in all_matches:
            if not match.get("result_winner"):
                continue
            date = match.get("date", "")
            kickoff = match.get("kickoff", "00:00")
            try:
                day = int(date.replace("June ", ""))
                hour = int(kickoff.split(":")[0])
            except:
                continue
            session_label = f"June {day}" if hour >= 18 else f"June {day - 1}"
            if session_label not in all_session_scores:
                all_session_scores[session_label] = {p: 0 for p in players}
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if not pred:
                    continue
                pts = 0
                winner_ok = pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower()
                scorer_ok = pred.get("scorer", "").strip() == match.get("result_scorer", "").strip()
                if winner_ok and scorer_ok:
                    pts = 3
                elif winner_ok:
                    pts = 1
                elif scorer_ok:
                    pts = 1
                all_session_scores[session_label][player] = all_session_scores[session_label].get(player, 0) + pts

        # Find all-time record (best single session score)
        all_time_record = 0
        all_time_record_holder = ""
        all_time_record_session = ""
        # Get current session label
        if now_ist.hour >= 18:
            current_session = f"June {now_ist.day}"
        else:
            current_session = f"June {now_ist.day - 1}"

        for session_label, scores_dict in all_session_scores.items():
            if session_label == current_session:
                continue  # skip current session for record comparison
            for player, pts in scores_dict.items():
                if pts > all_time_record:
                    all_time_record = pts
                    all_time_record_holder = player
                    all_time_record_session = session_label

        # Check if today's king beat the record
        if today_scores and all_time_record > 0:
            today_max = max(today_scores.values())
            if today_max > all_time_record:
                today_kings = [p for p, pts in today_scores.items() if pts == today_max]
                # Calculate accuracy: points earned / max possible (matches × 3)
                king_name = today_kings[0]
                king_matches = 0
                # Count how many completed matches in this session the king predicted
                if now_ist.hour >= 18:
                    sess_dates = [f"June {now_ist.day}", f"June {now_ist.day + 1}"]
                else:
                    sess_dates = [f"June {now_ist.day - 1}", f"June {now_ist.day}"]
                for match in all_matches:
                    if not match.get("result_winner"):
                        continue
                    try:
                        day = int(match["date"].replace("June ", ""))
                        hour = int(match.get("kickoff", "0").split(":")[0])
                        s_label = f"June {day}" if hour >= 18 else f"June {day - 1}"
                    except:
                        continue
                    if s_label != current_session:
                        continue
                    pred = predictions.get(king_name, {}).get(match["id"])
                    if pred:
                        king_matches += 1
                max_possible = king_matches * 3
                king_accuracy = round(today_max * 100 / max_possible) if max_possible > 0 else 0
                record_alert = {
                    "names": today_kings,
                    "points": today_max,
                    "prev_holder": all_time_record_holder,
                    "prev_points": all_time_record,
                    "accuracy": king_accuracy,
                }

        # --- Hot Takes: players who picked against the crowd and got it right ---
        from collections import Counter as HotTakeCounter
        hot_takes = []
        # Check recent completed matches (last 8)
        recent_completed = get_completed_matches()[-8:]
        for match in recent_completed:
            match_preds = []
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if pred and pred.get("winner"):
                    match_preds.append(pred["winner"].strip())
            if len(match_preds) < 5:
                continue
            counts = HotTakeCounter(match_preds)
            total = len(match_preds)
            actual_winner = match["result_winner"].strip()
            # Find players who predicted the actual winner when 70%+ picked someone else
            actual_count = counts.get(actual_winner, 0)
            if actual_count == 0:
                continue
            majority_pct = round((total - actual_count) * 100 / total)
            if majority_pct >= 70:
                # Find who got it right (the contrarians)
                for player in players:
                    pred = predictions.get(player, {}).get(match["id"])
                    if pred and pred.get("winner", "").strip().lower() == actual_winner.lower():
                        hot_takes.append({
                            "player": player,
                            "match": match,
                            "pick": actual_winner,
                            "against_pct": majority_pct,
                        })
        # Limit to most recent 3 hot takes
        hot_takes = hot_takes[-3:]

        return render_template(
            "home.html",
            leaderboard=ranked_leaderboard_with_change,
            today_matches=upcoming_matches,
            locked_matches=locked_matches,
            completed=completed,
            players=players,
            all_predictions=all_predictions,
            recap=recap,
            today_scores=today_scores,
            today_predicted=len(today_predictors),
            yesterday_predicted=len(yesterday_predictors),
            total_players=len(players),
            not_predicted=[p for p in players if p not in today_predictors],
            prediction_king=prediction_king,
            record_alert=record_alert,
            hot_takes=hot_takes,
            player_teams=player_teams,
            announcements=load_announcements(),
        )
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/health")
def health():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM matches")
        match_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM players")
        player_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM predictions")
        pred_count = cur.fetchone()[0]
        conn.close()
        return f"OK - Matches: {match_count}, Players: {player_count}, Predictions: {pred_count}"
    except Exception as e:
        return f"DB Error: {e}", 500


@app.route("/debug/today")
def debug_today():
    """Debug endpoint to check why today's matches aren't showing."""
    now_ist = datetime.now(IST)
    matches = load_matches()
    if now_ist.hour >= 10:
        today_date = f"June {now_ist.day}"
        tomorrow_date = f"June {now_ist.day + 1}"
    else:
        today_date = f"June {now_ist.day - 1}"
        tomorrow_date = f"June {now_ist.day}"

    candidates = []
    for m in matches:
        if m.get("result_winner"):
            continue
        if not m.get("kickoff"):
            continue
        try:
            hour = int(m["kickoff"].split(":")[0])
        except:
            continue
        if m.get("date") == today_date and hour >= 18:
            candidates.append(f"{m['id']}: {m['team_a']} vs {m['team_b']} | {m['date']} {m['kickoff']} | EVENING")
        elif m.get("date") == tomorrow_date and hour < 10:
            candidates.append(f"{m['id']}: {m['team_a']} vs {m['team_b']} | {m['date']} {m['kickoff']} | MORNING")

    info = f"Now IST: {now_ist.strftime('%Y-%m-%d %H:%M')}\n"
    info += f"today_date: {today_date}\n"
    info += f"tomorrow_date: {tomorrow_date}\n"
    info += f"Total matches in DB: {len(matches)}\n"
    info += f"Matches without result: {len([m for m in matches if not m.get('result_winner')])}\n"
    info += f"\nTonight's candidates ({len(candidates)}):\n"
    info += "\n".join(candidates) if candidates else "NONE FOUND"
    return f"<pre>{info}</pre>"


@app.route("/predict", methods=["GET", "POST"])
def predict():
    try:
        return _predict()
    except Exception as e:
        return f"Predict Error: {e}", 500


@app.route("/predict/verify", methods=["POST"])
def verify_pin():
    """AJAX endpoint to verify a player's PIN."""
    try:
        player = request.form.get("player", "").strip()
        pin = request.form.get("pin", "").strip()
        if not player or not pin:
            return jsonify({"ok": False})
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT pin FROM players WHERE name = %s", (player,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return jsonify({"ok": False})
        if not row[0]:
            # No PIN set — allow through (they'll be asked to set one)
            return jsonify({"ok": True, "no_pin": True})
        if pin == row[0]:
            return jsonify({"ok": True})
        return jsonify({"ok": False})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/predict/load", methods=["POST", "GET"])
def load_predictions_for_player():
    """AJAX endpoint to load existing predictions for a player."""
    try:
        player = request.args.get("player", "") or request.form.get("player", "")
        player = player.strip()
        if not player or player == "__new__":
            return jsonify({})
        predictions = load_predictions()
        player_preds = predictions.get(player, {})
        return jsonify(player_preds)
    except Exception as e:
        return jsonify({"error": str(e)})


def _predict():
    if request.method == "POST":
        action = request.form.get("action", "predict")

        # Handle PIN setup for existing players
        if action == "set_pin":
            player = request.form.get("player", "").strip()
            pin = request.form.get("pin", "").strip()
            if player and pin and len(pin) == 4 and pin.isdigit():
                conn = get_db()
                cur = conn.cursor()
                cur.execute("UPDATE players SET pin = %s WHERE name = %s", (pin, player))
                conn.commit()
                conn.close()
                flash(f"PIN set for {player}! Now you can predict.")
                return redirect(url_for("predict"))
            else:
                flash("PIN must be exactly 4 digits")
                return redirect(url_for("predict"))

        player = request.form.get("player", "").strip()
        new_player = request.form.get("new_player", "").strip()
        pin = request.form.get("pin", "").strip()

        if player == "__new__":
            if not new_player:
                flash("Please enter your name to register")
                return redirect(url_for("predict"))
            new_pin = request.form.get("new_pin", "").strip()
            if not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
                flash("Please set a 4-digit PIN")
                return redirect(url_for("predict"))
            player = new_player
            conn = get_db()
            cur = conn.cursor()
            cur.execute("INSERT INTO players (name, pin) VALUES (%s, %s) ON CONFLICT DO NOTHING", (player, new_pin))
            conn.commit()
            conn.close()
        else:
            if not player:
                flash("Please select your name")
                return redirect(url_for("predict"))
            # Verify PIN
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT pin FROM players WHERE name = %s", (player,))
            row = cur.fetchone()
            conn.close()
            if row[0]:
                # Player has a PIN set — verify it
                if pin != row[0]:
                    flash("Wrong PIN! Try again.")
                    return redirect(url_for("predict"))
            else:
                # Player exists but no PIN — redirect to set PIN
                return render_template("set_pin.html", player=player)

        today_matches = get_today_matches()
        conn = get_db()
        cur = conn.cursor()
        for match in today_matches:
            if is_match_locked(match):
                continue
            winner = request.form.get(f"winner_{match['id']}", "").strip()
            scorer = request.form.get(f"scorer_{match['id']}", "").strip()
            if scorer:
                import re
                scorer = re.sub(r'\s*[-_:]\s*', '-', scorer)
                scorer = re.sub(r'\s+', '-', scorer)
            if winner or scorer:
                cur.execute("""
                    INSERT INTO predictions (player, match_id, winner, scorer)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (player, match_id) DO UPDATE SET winner = %s, scorer = %s
                """, (player, match["id"], winner, scorer, winner, scorer))
        conn.commit()
        conn.close()
        flash(f"Predictions saved for {player}! 🎯")
        return redirect(url_for("my_today", player_name=player))

    today_matches = get_today_matches()
    players = load_players()
    for match in today_matches:
        match["locked"] = is_match_locked(match)
    
    # Load existing predictions for pre-filling the form
    predictions = load_predictions()
    player_preds = {}
    for player in players:
        player_preds[player] = predictions.get(player, {})
    
    return render_template("predict.html", matches=today_matches, players=players, player_preds=player_preds)


@app.route("/reminder")
def reminder():
    """Generate a copy-paste WhatsApp reminder message."""
    try:
        today_matches = get_today_matches()
        players = load_players()
        predictions = load_predictions()
        player_teams = load_player_teams()

        # Who predicted today
        today_predictors = set()
        for match in today_matches:
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if pred:
                    today_predictors.add(player)
        not_predicted = [p for p in players if p not in today_predictors]

        # Build reminder text
        lines = ["🎯 *Predictions open!*", ""]
        lines.append("Tonight's matches:")
        for match in today_matches:
            flag_a = FLAGS.get(match["team_a"], "🏳️")
            flag_b = FLAGS.get(match["team_b"], "🏳️")
            time_str = format_time_12h(match.get("kickoff", ""))
            lines.append(f"{flag_a} {match['team_a']} vs {match['team_b']} {flag_b} ({time_str} IST)")

        lines.append("")
        lines.append(f"Predict now 👉 https://wc-predictions-whsi.onrender.com/predict")

        reminder_text = "\n".join(lines)
        return render_template("reminder.html", reminder_text=reminder_text, today_matches=today_matches, not_predicted=not_predicted, total_players=len(players), predicted_count=len(today_predictors))
    except Exception as e:
        return f"Reminder Error: {e}", 500


@app.route("/profile", methods=["GET", "POST"])
def profile():
    """Let players set a nickname/alias that shows alongside their name."""
    if request.method == "POST":
        player = request.form.get("player", "").strip()
        pin = request.form.get("pin", "").strip()
        nickname = request.form.get("nickname", "").strip()

        if not player or not pin:
            flash("Please fill in all fields")
            return redirect(url_for("profile"))

        # Verify PIN
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT pin FROM players WHERE name = %s", (player,))
        row = cur.fetchone()
        if not row:
            conn.close()
            flash("Player not found")
            return redirect(url_for("profile"))
        if row[0] and pin != row[0]:
            conn.close()
            flash("Wrong PIN!")
            return redirect(url_for("profile"))

        # Update nickname
        cur.execute("UPDATE players SET nickname = %s WHERE name = %s", (nickname, player))
        conn.commit()
        conn.close()
        if nickname:
            flash(f"Nickname set: {player} ({nickname}) ✅")
        else:
            flash(f"Nickname removed for {player} ✅")
        return redirect(url_for("home"))

    players = load_players()
    return render_template("profile.html", players=players)


@app.route("/my-picks", methods=["GET", "POST"])
def my_picks():
    """Let players quickly check their tonight's predictions."""
    if request.method == "POST":
        player = request.form.get("player", "").strip()
        if player:
            return redirect(url_for("my_today", player_name=player))
    players = load_players()
    return render_template("my_picks.html", players=players)


@app.route("/my/today/<player_name>")
def my_today(player_name):
    """Show a player's predictions for tonight's session."""
    today_matches = get_today_matches()
    # Also include locked matches (already started)
    all_session_matches = today_matches
    predictions = load_predictions()
    player_preds = predictions.get(player_name, {})

    picks = []
    for match in all_session_matches:
        pred = player_preds.get(match["id"])
        if pred:
            picks.append({
                "match": match,
                "winner": pred.get("winner", ""),
                "scorer": pred.get("scorer", ""),
            })

    return render_template("my_today.html", player=player_name, picks=picks)


@app.route("/my/<player_name>")
def my_predictions(player_name):
    matches = load_matches()
    predictions = load_predictions()
    player_preds = predictions.get(player_name, {})
    
    history = []
    total_points = 0
    for match in matches:
        pred = player_preds.get(match["id"])
        if not pred:
            continue
        points = 0
        status = "pending"
        if match.get("result_winner"):
            status = "scored"
            if pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower():
                points += 1
            if pred.get("scorer", "").strip() == match.get("result_scorer", "").strip():
                points += 1
            if points == 2:
                points = 3
        total_points += points
        history.append({
            "match": match,
            "pred": pred,
            "points": points,
            "status": status,
        })
    
    return render_template("my_predictions.html", player=player_name, history=history, total_points=total_points)


@app.route("/fav", methods=["GET", "POST"])
def set_fav_team():
    if request.method == "POST":
        player = request.form.get("player", "").strip()
        pin = request.form.get("pin", "").strip()
        team = request.form.get("team", "").strip()
        
        if not player or not team:
            flash("Please select your name and a team")
            return redirect(url_for("set_fav_team"))
        
        # Verify PIN
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT pin FROM players WHERE name = %s", (player,))
        row = cur.fetchone()
        if not row:
            conn.close()
            flash("Player not found")
            return redirect(url_for("set_fav_team"))
        if row[0] and pin != row[0]:
            conn.close()
            flash("Wrong PIN!")
            return redirect(url_for("set_fav_team"))
        
        cur.execute("UPDATE players SET fav_team = %s WHERE name = %s", (team, player))
        conn.commit()
        conn.close()
        flash(f"🏳️ {player} supports {FLAGS.get(team, '')} {team}!")
        return redirect(url_for("home"))
    
    players = load_players()
    teams = sorted(FLAGS.keys())
    return render_template("fav_team.html", players=players, teams=teams, flags=FLAGS)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not request.cookies.get("admin_auth") == "true":
        if request.method == "POST" and request.form.get("action") == "login":
            if request.form.get("password") == ADMIN_PASSWORD:
                resp = redirect(url_for("admin"))
                resp.set_cookie("admin_auth", "true", max_age=86400)
                return resp
            else:
                flash("Wrong password!")
                return redirect(url_for("admin"))
        return render_template("admin_login.html")

    if request.method == "POST":
        action = request.form.get("action")
        conn = get_db()
        cur = conn.cursor()

        if action == "add_match":
            match_id = f"match_{int(datetime.now().timestamp())}"
            cur.execute(
                "INSERT INTO matches (id, team_a, team_b, date, sort_order) VALUES (%s, %s, %s, %s, %s)",
                (match_id, request.form.get("team_a", "").strip(),
                 request.form.get("team_b", "").strip(),
                 request.form.get("date", "").strip(), 999),
            )
            conn.commit()
            flash("Match added!")

        elif action == "update_result":
            match_id = request.form.get("match_id")
            winner = request.form.get("result_winner", "").strip()
            scorer = request.form.get("result_scorer", "").strip()
            cur.execute(
                "UPDATE matches SET result_winner = %s, result_scorer = %s WHERE id = %s",
                (winner, scorer, match_id),
            )
            conn.commit()
            flash("Result updated! Leaderboard recalculated. ✅")

        elif action == "delete_match":
            match_id = request.form.get("match_id")
            cur.execute("DELETE FROM matches WHERE id = %s", (match_id,))
            cur.execute("DELETE FROM predictions WHERE match_id = %s", (match_id,))
            conn.commit()
            flash("Match deleted!")

        elif action == "edit_match":
            match_id = request.form.get("match_id")
            date = request.form.get("date", "").strip()
            kickoff = request.form.get("kickoff", "").strip()
            team_a = request.form.get("team_a", "").strip()
            team_b = request.form.get("team_b", "").strip()
            if date and kickoff:
                cur.execute("UPDATE matches SET date = %s, kickoff = %s WHERE id = %s", (date, kickoff, match_id))
            if team_a:
                cur.execute("UPDATE matches SET team_a = %s WHERE id = %s", (team_a, match_id))
            if team_b:
                cur.execute("UPDATE matches SET team_b = %s WHERE id = %s", (team_b, match_id))
            conn.commit()
            flash("Match updated!")

        elif action == "delete_player":
            name = request.form.get("player_name", "").strip()
            cur.execute("DELETE FROM players WHERE name = %s", (name,))
            cur.execute("DELETE FROM predictions WHERE player = %s", (name,))
            conn.commit()
            flash(f"Player '{name}' removed!")

        elif action == "reset_pin":
            name = request.form.get("player_name", "").strip()
            cur.execute("UPDATE players SET pin = '' WHERE name = %s", (name,))
            conn.commit()
            flash(f"PIN reset for '{name}'. They can set a new one next time.")

        elif action == "broadcast":
            message = request.form.get("message", "").strip()
            if message:
                cur.execute("INSERT INTO announcements (message) VALUES (%s)", (message,))
                conn.commit()
                flash(f"Announcement posted! 📢")

        elif action == "clear_announcements":
            cur.execute("UPDATE announcements SET active = FALSE")
            conn.commit()
            flash("All announcements cleared.")

        elif action == "bulk_results":
            # Process multiple match results at once
            updated = 0
            for key in request.form:
                if key.startswith("winner_"):
                    match_id = key.replace("winner_", "")
                    winner = request.form.get(f"winner_{match_id}", "").strip()
                    scorer = request.form.get(f"scorer_{match_id}", "").strip()
                    if winner:
                        cur.execute(
                            "UPDATE matches SET result_winner = %s, result_scorer = %s WHERE id = %s",
                            (winner, scorer, match_id),
                        )
                        updated += 1
            if updated:
                conn.commit()
                flash(f"Updated results for {updated} match(es)! ✅")

        conn.close()
        return redirect(url_for("admin"))

    matches = load_matches()
    now_ist = datetime.now(IST)
    today_day = now_ist.day
    # Only show today's session matches in admin (not old ones)
    # Show matches from today and tomorrow (for the current session)
    if now_ist.hour < 10:
        show_dates = [f"June {today_day - 1}", f"June {today_day}"]
    else:
        show_dates = [f"June {today_day}", f"June {today_day + 1}"]
    pending = [m for m in matches if m.get("date") in show_dates and not m.get("result_winner")]
    players = load_players()
    predictions = load_predictions()
    # Get predictions for pending matches (for the "view predictions" feature)
    match_predictions = {}
    for match in pending:
        match_predictions[match["id"]] = {}
        for player in players:
            pred = predictions.get(player, {}).get(match["id"])
            if pred:
                match_predictions[match["id"]][player] = pred
    announcements = load_announcements()
    return render_template("admin.html", data={"players": players}, today_matches=get_today_matches(), pending=pending, match_predictions=match_predictions, announcements=announcements)


@app.route("/stats")
def stats():
    """Statistics page with graphs and prediction analytics."""
    from collections import Counter
    try:
        matches = load_matches()
        players = load_players()
        predictions = load_predictions()
        player_teams = load_player_teams()

        completed_matches = [m for m in matches if m.get("result_winner")]
        total_completed = len(completed_matches)

        # --- Per-player accuracy stats ---
        player_stats = {}
        for player in players:
            total_preds = 0
            correct_winners = 0
            correct_scorers = 0
            perfect = 0  # both correct
            points = 0
            for match in completed_matches:
                pred = predictions.get(player, {}).get(match["id"])
                if not pred:
                    continue
                total_preds += 1
                winner_ok = pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower()
                scorer_ok = pred.get("scorer", "").strip() == match.get("result_scorer", "").strip()
                if winner_ok:
                    correct_winners += 1
                if scorer_ok:
                    correct_scorers += 1
                if winner_ok and scorer_ok:
                    perfect += 1
                    points += 3
                elif winner_ok:
                    points += 1
                elif scorer_ok:
                    points += 1
            player_stats[player] = {
                "total_preds": total_preds,
                "correct_winners": correct_winners,
                "correct_scorers": correct_scorers,
                "perfect": perfect,
                "points": points,
                "winner_pct": round(correct_winners * 100 / total_preds, 1) if total_preds > 0 else 0,
                "scorer_pct": round(correct_scorers * 100 / total_preds, 1) if total_preds > 0 else 0,
            }

        # --- Points progression over matches (cumulative) ---
        points_over_time = {player: [] for player in players}
        match_labels = []
        for match in completed_matches:
            short_label = f"{match['team_a'][:3]} v {match['team_b'][:3]}"
            match_labels.append(short_label)
            for player in players:
                prev = points_over_time[player][-1] if points_over_time[player] else 0
                pred = predictions.get(player, {}).get(match["id"])
                pts = 0
                if pred:
                    winner_ok = pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower()
                    scorer_ok = pred.get("scorer", "").strip() == match.get("result_scorer", "").strip()
                    if winner_ok and scorer_ok:
                        pts = 3
                    elif winner_ok:
                        pts = 1
                    elif scorer_ok:
                        pts = 1
                points_over_time[player].append(prev + pts)

        # --- Most predicted teams (across all predictions) ---
        team_pick_counts = {}
        total_picks = 0
        for player in players:
            for match_id, pred in predictions.get(player, {}).items():
                winner = pred.get("winner", "").strip()
                if winner:
                    team_pick_counts[winner] = team_pick_counts.get(winner, 0) + 1
                    total_picks += 1

        # Sort by picks descending, top 10
        top_teams = sorted(team_pick_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        # --- Upset detection: matches where most predicted team lost ---
        upsets = []
        for match in completed_matches:
            match_preds = []
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if pred and pred.get("winner"):
                    match_preds.append(pred["winner"].strip())
            if not match_preds:
                continue
            # Most predicted winner
            counts = Counter(match_preds)
            most_predicted, most_count = counts.most_common(1)[0]
            pct = round(most_count * 100 / len(match_preds))
            actual = match["result_winner"].strip()
            if most_predicted.lower() != actual.lower() and pct >= 50:
                upsets.append({
                    "match": match,
                    "predicted": most_predicted,
                    "predicted_pct": pct,
                    "actual": actual,
                })

        # --- Daily session breakdown (who predicted, who didn't, per-day %) ---
        # Group matches by SESSION (evening of day X + morning of day X+1 = "Session Jun X")
        # This matches the home page logic
        sessions = {}  # session label -> list of match ids
        for match in matches:
            date = match.get("date", "")
            kickoff = match.get("kickoff", "00:00")
            try:
                day = int(date.replace("June ", ""))
                hour = int(kickoff.split(":")[0])
            except:
                continue
            # Evening matches (>=18:00) belong to that day's session
            # Morning matches (<10:00) belong to previous day's session
            if hour >= 18:
                session_label = f"June {day}"
            else:
                session_label = f"June {day - 1}"
            if session_label not in sessions:
                sessions[session_label] = []
            sessions[session_label].append(match["id"])

        daily_breakdown = []
        sorted_dates = sorted(sessions.keys(), key=lambda d: int(d.replace("June ", "")))
        for date in sorted_dates:
            match_ids = sessions[date]
            predicted_players = set()
            not_predicted_players = set()
            for player in players:
                player_predicted = False
                for mid in match_ids:
                    if predictions.get(player, {}).get(mid):
                        player_predicted = True
                        break
                if player_predicted:
                    predicted_players.add(player)
                else:
                    not_predicted_players.add(player)
            pct = round(len(predicted_players) * 100 / len(players)) if players else 0
            # Only include sessions where at least someone predicted (hide pre-launch days)
            if len(predicted_players) > 0:
                daily_breakdown.append({
                    "date": date,
                    "predicted": sorted(predicted_players),
                    "not_predicted": sorted(not_predicted_players),
                    "predicted_count": len(predicted_players),
                    "total": len(players),
                    "pct": pct,
                })

        # --- Participation rate per match day (for chart) ---
        participation_labels = [d["date"] for d in daily_breakdown]
        participation_rates = [d["pct"] for d in daily_breakdown]

        # --- Prediction streaks (consecutive matches predicted) ---
        # Count consecutive matches a player predicted (based on match order)
        player_streaks = {}
        # Sort completed + pending matches by sort_order/id to get chronological order
        all_matches_sorted = sorted(matches, key=lambda m: m.get("sort_order", 0))
        for player in players:
            current_streak = 0
            max_streak = 0
            started = False
            for match in all_matches_sorted:
                pred = predictions.get(player, {}).get(match["id"])
                if pred:
                    started = True
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                elif started:
                    current_streak = 0
            player_streaks[player] = {"current": current_streak, "max": max_streak}

        # --- Daily accuracy (winner accuracy per day for completed matches) ---
        daily_accuracy = []
        for date in sorted_dates:
            match_ids = sessions[date]
            day_completed = [m for m in completed_matches if m["id"] in match_ids]
            if not day_completed:
                continue
            total_preds_day = 0
            correct_preds_day = 0
            for match in day_completed:
                for player in players:
                    pred = predictions.get(player, {}).get(match["id"])
                    if pred and pred.get("winner"):
                        total_preds_day += 1
                        if pred["winner"].strip().lower() == match["result_winner"].strip().lower():
                            correct_preds_day += 1
            acc = round(correct_preds_day * 100 / total_preds_day) if total_preds_day > 0 else 0
            daily_accuracy.append({"date": date, "accuracy": acc, "total": total_preds_day, "correct": correct_preds_day})

        daily_accuracy_labels = [d["date"] for d in daily_accuracy]
        daily_accuracy_values = [d["accuracy"] for d in daily_accuracy]

        # --- Player points per day (for stacked/grouped bar chart) ---
        player_daily_points = {player: [] for player in players}
        for date in sorted_dates:
            match_ids = sessions[date]
            day_completed = [m for m in completed_matches if m["id"] in match_ids]
            for player in players:
                day_pts = 0
                for match in day_completed:
                    pred = predictions.get(player, {}).get(match["id"])
                    if pred:
                        winner_ok = pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower()
                        scorer_ok = pred.get("scorer", "").strip() == match.get("result_scorer", "").strip()
                        if winner_ok and scorer_ok:
                            day_pts += 3
                        elif winner_ok:
                            day_pts += 1
                        elif scorer_ok:
                            day_pts += 1
                player_daily_points[player].append(day_pts)

        # Filter to only days with results
        days_with_results = [i for i, date in enumerate(sorted_dates) if any(m for m in completed_matches if m["id"] in sessions[date])]
        daily_points_labels = [sorted_dates[i] for i in days_with_results]
        player_daily_points_filtered = {player: [player_daily_points[player][i] for i in days_with_results] for player in players}

        # --- Overall stats summary ---
        total_predictions_made = sum(1 for p in players for m in matches if predictions.get(p, {}).get(m["id"]))
        overall_winner_accuracy = 0
        overall_scorer_accuracy = 0
        total_scored_preds = 0
        for player in players:
            for match in completed_matches:
                pred = predictions.get(player, {}).get(match["id"])
                if pred:
                    total_scored_preds += 1
                    if pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower():
                        overall_winner_accuracy += 1
                    if pred.get("scorer", "").strip() == match.get("result_scorer", "").strip():
                        overall_scorer_accuracy += 1

        summary = {
            "total_matches": len(matches),
            "completed_matches": total_completed,
            "total_players": len(players),
            "total_predictions": total_predictions_made,
            "overall_winner_pct": round(overall_winner_accuracy * 100 / total_scored_preds, 1) if total_scored_preds > 0 else 0,
            "overall_scorer_pct": round(overall_scorer_accuracy * 100 / total_scored_preds, 1) if total_scored_preds > 0 else 0,
        }

        # --- RECORDS ---
        # Build session scores for all players across all sessions
        all_session_data = {}  # {session_label: {player: {points, perfects, predicted_count}}}
        for match in completed_matches:
            date = match.get("date", "")
            kickoff = match.get("kickoff", "00:00")
            try:
                day = int(date.replace("June ", ""))
                hour = int(kickoff.split(":")[0])
            except:
                continue
            session_label = f"June {day}" if hour >= 18 else f"June {day - 1}"
            if session_label not in all_session_data:
                all_session_data[session_label] = {p: {"points": 0, "perfects": 0, "predicted": 0, "matches": 0} for p in players}
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if not pred:
                    continue
                all_session_data[session_label][player]["predicted"] += 1
                all_session_data[session_label][player]["matches"] += 1
                winner_ok = pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower()
                scorer_ok = pred.get("scorer", "").strip() == match.get("result_scorer", "").strip()
                if winner_ok and scorer_ok:
                    all_session_data[session_label][player]["points"] += 3
                    all_session_data[session_label][player]["perfects"] += 1
                elif winner_ok:
                    all_session_data[session_label][player]["points"] += 1
                elif scorer_ok:
                    all_session_data[session_label][player]["points"] += 1

        # Also count total matches per session (for accuracy calc)
        session_match_counts = {}
        for match in completed_matches:
            date = match.get("date", "")
            kickoff = match.get("kickoff", "00:00")
            try:
                day = int(date.replace("June ", ""))
                hour = int(kickoff.split(":")[0])
            except:
                continue
            session_label = f"June {day}" if hour >= 18 else f"June {day - 1}"
            session_match_counts[session_label] = session_match_counts.get(session_label, 0) + 1

        records = {}

        # 1. Best session score
        best_session_score = 0
        best_session_score_holders = []
        best_session_score_date = ""
        for session_label, player_data in all_session_data.items():
            for player, data in player_data.items():
                if data["points"] > best_session_score:
                    best_session_score = data["points"]
                    best_session_score_holders = [player]
                    best_session_score_date = session_label
                elif data["points"] == best_session_score and data["points"] > 0:
                    if player not in best_session_score_holders:
                        best_session_score_holders.append(player)
        records["best_session"] = {"player": ", ".join(best_session_score_holders) if best_session_score_holders else "-", "value": best_session_score, "date": best_session_score_date}

        # 2. Most perfect predictions in one session
        most_perfects = 0
        most_perfects_holders = []
        most_perfects_date = ""
        for session_label, player_data in all_session_data.items():
            for player, data in player_data.items():
                if data["perfects"] > most_perfects:
                    most_perfects = data["perfects"]
                    most_perfects_holders = [player]
                    most_perfects_date = session_label
                elif data["perfects"] == most_perfects and data["perfects"] > 0:
                    if player not in most_perfects_holders:
                        most_perfects_holders.append(player)
        records["most_perfects"] = {"player": ", ".join(most_perfects_holders) if most_perfects_holders else "-", "value": most_perfects, "date": most_perfects_date}

        # 3. Highest session accuracy (points/max possible, min 3 matches predicted)
        best_accuracy = 0
        best_accuracy_holders = []
        best_accuracy_date = ""
        for session_label, player_data in all_session_data.items():
            for player, data in player_data.items():
                if data["predicted"] >= 3:
                    max_possible = data["predicted"] * 3
                    acc = round(data["points"] * 100 / max_possible) if max_possible > 0 else 0
                    if acc > best_accuracy:
                        best_accuracy = acc
                        best_accuracy_holders = [player]
                        best_accuracy_date = session_label
                    elif acc == best_accuracy and acc > 0:
                        if player not in best_accuracy_holders:
                            best_accuracy_holders.append(player)
        records["best_accuracy"] = {"player": ", ".join(best_accuracy_holders) if best_accuracy_holders else "-", "value": f"{best_accuracy}%", "date": best_accuracy_date}

        # 4. Longest prediction streak
        longest_streak = 0
        longest_streak_holders = []
        for player in players:
            if player_streaks[player]["max"] > longest_streak:
                longest_streak = player_streaks[player]["max"]
                longest_streak_holders = [player]
            elif player_streaks[player]["max"] == longest_streak and longest_streak > 0:
                longest_streak_holders.append(player)
        records["longest_streak"] = {"player": ", ".join(longest_streak_holders) if longest_streak_holders else "-", "value": f"{longest_streak} matches"}

        # 5. Most King of the Day wins
        king_wins = {p: 0 for p in players}
        for session_label, player_data in all_session_data.items():
            session_max = 0
            for player, data in player_data.items():
                if data["points"] > session_max and data["points"] >= 3:
                    session_max = data["points"]
            # All players with session_max get a crown for this session
            if session_max >= 3:
                for player, data in player_data.items():
                    if data["points"] == session_max:
                        king_wins[player] = king_wins.get(player, 0) + 1
        most_king_wins = max(king_wins.values()) if king_wins else 0
        most_king_holder = [p for p, w in king_wins.items() if w == most_king_wins and w > 0]
        records["most_kings"] = {"player": ", ".join(most_king_holder) if most_king_holder else "-", "value": most_king_wins}

        # 6. Most perfect predictions overall
        total_perfects_per_player = {}
        for player in players:
            total_p = 0
            for session_label, player_data in all_session_data.items():
                total_p += player_data.get(player, {}).get("perfects", 0)
            total_perfects_per_player[player] = total_p
        most_total_perfects = max(total_perfects_per_player.values()) if total_perfects_per_player else 0
        most_total_perfects_holder = [p for p, v in total_perfects_per_player.items() if v == most_total_perfects and v > 0]
        records["most_total_perfects"] = {"player": ", ".join(most_total_perfects_holder) if most_total_perfects_holder else "-", "value": most_total_perfects}

        # 7. Biggest rank jump (using leaderboard rank changes from home)
        # We'll compute per-session rank changes
        biggest_jump = 0
        biggest_jump_holders = []
        biggest_jump_date = ""
        cumulative_points = {p: 0 for p in players}
        for session_label in sorted(all_session_data.keys(), key=lambda d: int(d.replace("June ", ""))):
            # Previous ranks
            sorted_prev = sorted(cumulative_points.items(), key=lambda x: x[1], reverse=True)
            prev_r = {}
            r = 0
            prev_v = None
            for i, (p, pts) in enumerate(sorted_prev):
                if pts != prev_v:
                    r += 1
                    prev_v = pts
                prev_r[p] = r
            # Add session points
            for player in players:
                cumulative_points[player] += all_session_data[session_label].get(player, {}).get("points", 0)
            # New ranks
            sorted_new = sorted(cumulative_points.items(), key=lambda x: x[1], reverse=True)
            new_r = {}
            r = 0
            prev_v = None
            for i, (p, pts) in enumerate(sorted_new):
                if pts != prev_v:
                    r += 1
                    prev_v = pts
                new_r[p] = r
            # Check jumps
            for player in players:
                jump = prev_r.get(player, 0) - new_r.get(player, 0)
                if jump > biggest_jump:
                    biggest_jump = jump
                    biggest_jump_holders = [player]
                    biggest_jump_date = session_label
                elif jump == biggest_jump and jump > 0:
                    biggest_jump_holders.append(player)
        biggest_jump_holders = list(dict.fromkeys(biggest_jump_holders))
        records["biggest_jump"] = {"player": ", ".join(biggest_jump_holders) if biggest_jump_holders else "-", "value": f"↑{biggest_jump} spots", "date": biggest_jump_date}

        # 8. Worst session (0 pts while predicting all matches in session)
        worst_session_holders = []
        worst_session_date = ""
        for session_label, player_data in all_session_data.items():
            total_matches_in_session = session_match_counts.get(session_label, 0)
            if total_matches_in_session < 2:
                continue
            for player, data in player_data.items():
                if data["predicted"] == total_matches_in_session and data["points"] == 0:
                    if player not in worst_session_holders:
                        worst_session_holders.append(player)
                    worst_session_date = session_label
        # Only show if 3 or fewer people (otherwise it's not a notable record)
        if len(worst_session_holders) > 3:
            worst_session_holders = []
            worst_session_date = ""
        records["worst_session"] = {"player": ", ".join(worst_session_holders) if worst_session_holders else "-", "value": "0 pts (all predicted)", "date": worst_session_date if worst_session_holders else ""}

        # 9. Longest drought (most consecutive predictions without scoring)
        longest_drought = 0
        longest_drought_holders = []
        for player in players:
            drought = 0
            max_drought = 0
            for match in completed_matches:
                pred = predictions.get(player, {}).get(match["id"])
                if not pred:
                    continue
                winner_ok = pred.get("winner", "").strip().lower() == match["result_winner"].strip().lower()
                scorer_ok = pred.get("scorer", "").strip() == match.get("result_scorer", "").strip()
                pts = 0
                if winner_ok and scorer_ok:
                    pts = 3
                elif winner_ok:
                    pts = 1
                elif scorer_ok:
                    pts = 1
                if pts == 0:
                    drought += 1
                    max_drought = max(max_drought, drought)
                else:
                    drought = 0
            if max_drought > longest_drought:
                longest_drought = max_drought
                longest_drought_holders = [player]
            elif max_drought == longest_drought and longest_drought > 0:
                longest_drought_holders.append(player)
        records["longest_drought"] = {"player": ", ".join(longest_drought_holders) if longest_drought_holders else "-", "value": f"{longest_drought} matches"}

        # 10. Best draw predictor
        draw_correct = {p: 0 for p in players}
        for match in completed_matches:
            if match["result_winner"].strip().lower() != "draw":
                continue
            for player in players:
                pred = predictions.get(player, {}).get(match["id"])
                if pred and pred.get("winner", "").strip().lower() == "draw":
                    draw_correct[player] += 1
        max_draws = max(draw_correct.values()) if draw_correct else 0
        best_draw_holders = [p for p, v in draw_correct.items() if v == max_draws and v > 0]
        records["best_draw"] = {"player": ", ".join(best_draw_holders) if best_draw_holders else "-", "value": max_draws}

        # 11. Overall leader
        overall_leader = ""
        overall_leader_pts = 0
        overall_pts = {p: 0 for p in players}
        for session_label, player_data in all_session_data.items():
            for player, data in player_data.items():
                overall_pts[player] += data["points"]
        if overall_pts:
            overall_leader_pts = max(overall_pts.values())
            overall_leader = [p for p, v in overall_pts.items() if v == overall_leader_pts]
        records["overall_leader"] = {"player": ", ".join(overall_leader) if overall_leader else "-", "value": f"{overall_leader_pts} pts"}

        return render_template(
            "stats.html",
            summary=summary,
            player_stats=player_stats,
            players=players,
            player_teams=player_teams,
            points_over_time=points_over_time,
            match_labels=match_labels,
            top_teams=top_teams,
            total_picks=total_picks,
            upsets=upsets,
            participation_labels=participation_labels,
            participation_rates=participation_rates,
            daily_breakdown=daily_breakdown,
            player_streaks=player_streaks,
            daily_accuracy_labels=daily_accuracy_labels,
            daily_accuracy_values=daily_accuracy_values,
            daily_points_labels=daily_points_labels,
            player_daily_points=player_daily_points_filtered,
            records=records,
        )
    except Exception as e:
        return f"Stats Error: {e}", 500


def update_kickoff_times():
    """Update kickoff times (IST) from official fixture sheet.
    Times must match the team assignments in seed_matches().
    """
    # Match the exact team-time assignments from the seed data
    updates = [
        ("match_1", "June 12", "00:30"),   # Mexico vs South Africa
        ("match_2", "June 12", "07:30"),   # South Korea vs Czech Republic
        ("match_3", "June 13", "00:30"),   # Canada vs Bosnia & Herzegovina
        ("match_4", "June 13", "06:30"),   # USA vs Paraguay
        ("match_5", "June 14", "00:30"),   # Qatar vs Switzerland
        ("match_6", "June 14", "03:30"),   # Brazil vs Morocco
        ("match_7", "June 14", "06:30"),   # Haiti vs Scotland
        ("match_8", "June 14", "09:30"),   # Australia vs Turkey
        ("match_9", "June 14", "22:30"),   # Germany vs Curacao
        ("match_10", "June 15", "01:30"),  # Netherlands vs Japan (seed had 02:30, fixture=1:30 AM)
        ("match_11", "June 15", "04:30"),  # Ivory Coast vs Ecuador
        ("match_12", "June 15", "07:30"),  # Sweden vs Tunisia
        ("match_13", "June 15", "21:30"),  # Spain vs Cape Verde
        ("match_14", "June 16", "00:30"),  # Belgium vs Egypt
        ("match_15", "June 16", "03:30"),  # Saudi Arabia vs Uruguay
        ("match_16", "June 16", "06:30"),  # Iran vs New Zealand
        ("match_17", "June 17", "00:30"),  # France vs Senegal
        ("match_18", "June 17", "03:30"),  # Iraq vs Norway
        ("match_19", "June 17", "06:30"),  # Argentina vs Algeria
        ("match_20", "June 17", "09:30"),  # Austria vs Jordan
        ("match_21", "June 17", "22:30"),  # Portugal vs DR Congo
        ("match_22", "June 18", "07:30"),  # Uzbekistan vs Colombia
        ("match_23", "June 18", "01:30"),  # England vs Croatia
        ("match_24", "June 18", "04:30"),  # Ghana vs Panama
        ("match_25", "June 18", "21:30"),  # Czech Republic vs South Africa
        ("match_26", "June 19", "06:30"),  # Mexico vs South Korea
        ("match_27", "June 19", "00:30"),  # Switzerland vs Bosnia & Herzegovina
        ("match_28", "June 19", "03:30"),  # Canada vs Qatar
        ("match_29", "June 20", "03:30"),  # Scotland vs Morocco
        ("match_30", "June 20", "06:00"),  # Brazil vs Haiti (fixture says 6:30 but seed had 6:00)
        ("match_31", "June 20", "00:30"),  # USA vs Australia
        ("match_32", "June 20", "09:30"),  # Turkey vs Paraguay
        ("match_33", "June 21", "01:30"),  # Germany vs Ivory Coast
        ("match_34", "June 21", "05:30"),  # Ecuador vs Curacao
        ("match_35", "June 20", "22:30"),  # Netherlands vs Sweden
        ("match_36", "June 21", "09:30"),  # Tunisia vs Japan
        ("match_37", "June 22", "00:30"),  # Belgium vs Iran
        ("match_38", "June 22", "06:00"),  # New Zealand vs Egypt
        ("match_39", "June 21", "21:30"),  # Spain vs Saudi Arabia
        ("match_40", "June 22", "03:30"),  # Uruguay vs Cape Verde
        ("match_41", "June 23", "02:30"),  # France vs Iraq
        ("match_42", "June 23", "05:30"),  # Norway vs Senegal
        ("match_43", "June 22", "22:30"),  # Argentina vs Austria
        ("match_44", "June 23", "08:30"),  # Jordan vs Algeria
        ("match_45", "June 23", "22:30"),  # Portugal vs Uzbekistan
        ("match_46", "June 24", "06:30"),  # Colombia vs DR Congo
        ("match_47", "June 24", "00:30"),  # England vs Ghana
        ("match_48", "June 24", "03:30"),  # Panama vs Croatia
    ]
    conn = get_db()
    cur = conn.cursor()
    for match_id, date, kickoff in updates:
        cur.execute("UPDATE matches SET date = %s, kickoff = %s WHERE id = %s", (date, kickoff, match_id))
    conn.commit()
    conn.close()


# Initialize database on startup
init_db()
seed_matches()
update_kickoff_times()
# Note: Admin edits to times will be overwritten on restart.
# For permanent time changes, update the code in update_kickoff_times().


def add_matchday3_group_abc():
    """Add matchday 3 matches for all groups (matches 49-72)."""
    conn = get_db()
    cur = conn.cursor()
    new_matches = [
        # June 25 - Group B, C, A matchday 3 (simultaneous per group)
        ("match_49", "Switzerland", "Canada", "June 25", "06:30", 49),
        ("match_50", "Bosnia & Herzegovina", "Qatar", "June 25", "00:30", 50),
        ("match_51", "Morocco", "Haiti", "June 25", "03:30", 51),
        ("match_52", "Scotland", "Brazil", "June 25", "03:30", 52),
        ("match_53", "South Africa", "South Korea", "June 25", "06:30", 53),
        ("match_54", "Czech Republic", "Mexico", "June 25", "06:30", 54),
        # June 26 - Group E, F, D matchday 3
        ("match_55", "Curacao", "Ivory Coast", "June 26", "01:30", 55),
        ("match_56", "Ecuador", "Germany", "June 26", "01:30", 56),
        ("match_57", "Tunisia", "Netherlands", "June 26", "04:30", 57),
        ("match_58", "Japan", "Sweden", "June 26", "04:30", 58),
        ("match_59", "Turkey", "USA", "June 26", "07:30", 59),
        ("match_60", "Paraguay", "Australia", "June 26", "07:30", 60),
        # June 26-27 - Group I matchday 3
        ("match_61", "Norway", "France", "June 26", "12:30", 61),
        ("match_62", "Senegal", "Iraq", "June 27", "00:30", 62),
        # June 27 - Group H, G matchday 3
        ("match_63", "Cape Verde", "Saudi Arabia", "June 27", "05:30", 63),
        ("match_64", "Uruguay", "Spain", "June 27", "05:30", 64),
        ("match_65", "New Zealand", "Belgium", "June 27", "08:30", 65),
        ("match_66", "Egypt", "Iran", "June 27", "08:30", 66),
        # June 28 - Group L, K, J matchday 3
        ("match_67", "Panama", "England", "June 28", "02:30", 67),
        ("match_68", "Croatia", "Ghana", "June 28", "02:30", 68),
        ("match_69", "Colombia", "Portugal", "June 28", "05:00", 69),
        ("match_70", "DR Congo", "Uzbekistan", "June 28", "05:00", 70),
        ("match_71", "Algeria", "Austria", "June 28", "07:30", 71),
        ("match_72", "Jordan", "Argentina", "June 28", "07:30", 72),
    ]
    for m in new_matches:
        cur.execute("""
            INSERT INTO matches (id, team_a, team_b, date, kickoff, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET date = EXCLUDED.date, kickoff = EXCLUDED.kickoff, team_a = EXCLUDED.team_a, team_b = EXCLUDED.team_b
        """, m)
    conn.commit()
    conn.close()


add_matchday3_group_abc()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
