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
    # Add kickoff column if not exists (for existing databases)
    try:
        cur.execute("ALTER TABLE matches ADD COLUMN kickoff TEXT DEFAULT ''")
    except:
        conn.rollback()
    conn.commit()
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
    # Session dates for "king of the day" - check current AND previous session
    if now_ist.hour < 10:
        session_dates_current = [f"June {now_ist.day - 1}", f"June {now_ist.day}"]
        session_dates_prev = [f"June {now_ist.day - 2}", f"June {now_ist.day - 1}"]
    else:
        session_dates_current = [f"June {now_ist.day}", f"June {now_ist.day + 1}"]
        session_dates_prev = [f"June {now_ist.day - 1}", f"June {now_ist.day}"]
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
                # Only count matches with kickoff in the session window
                try:
                    hour = int(match.get("kickoff", "0").split(":")[0])
                    match_date = match.get("date", "")
                    if now_ist.hour >= 10:
                        if (match_date == f"June {now_ist.day}" and hour >= 18) or (match_date == f"June {now_ist.day + 1}" and hour < 10):
                            today_scores[player] = today_scores.get(player, 0) + points
                    else:
                        if (match_date == f"June {now_ist.day - 1}" and hour >= 18) or (match_date == f"June {now_ist.day}" and hour < 10):
                            today_scores[player] = today_scores.get(player, 0) + points
                except:
                    pass
            # Previous session
            if match.get("date") in session_dates_prev:
                try:
                    hour = int(match.get("kickoff", "0").split(":")[0])
                    match_date = match.get("date", "")
                    if now_ist.hour >= 10:
                        if (match_date == f"June {now_ist.day - 1}" and hour >= 18) or (match_date == f"June {now_ist.day}" and hour < 10):
                            prev_scores[player] = prev_scores.get(player, 0) + points
                    else:
                        if (match_date == f"June {now_ist.day - 2}" and hour >= 18) or (match_date == f"June {now_ist.day - 1}" and hour < 10):
                            prev_scores[player] = prev_scores.get(player, 0) + points
                except:
                    pass
    # Use previous session if current has no scores
    final_today = today_scores if max(today_scores.values(), default=0) > 0 else prev_scores
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

        # Find today's prediction king
        prediction_king = None
        king_points = 0
        if today_scores:
            max_pts = max(today_scores.values())
            if max_pts > 0:
                kings = [p for p, pts in today_scores.items() if pts == max_pts]
                prediction_king = {"names": kings, "points": max_pts}

        return render_template(
            "home.html",
            leaderboard=ranked_leaderboard,
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
            player_teams=player_teams,
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


@app.route("/predict", methods=["GET", "POST"])
def predict():
    try:
        return _predict()
    except Exception as e:
        return f"Predict Error: {e}", 500


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
        return redirect(url_for("home"))

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
            if date and kickoff:
                cur.execute("UPDATE matches SET date = %s, kickoff = %s WHERE id = %s", (date, kickoff, match_id))
                conn.commit()
                flash("Match time updated!")

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
    return render_template("admin.html", data={"players": players}, today_matches=get_today_matches(), pending=pending)


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
        # Group matches by session (evening + next morning)
        sessions = {}  # date label -> list of match ids
        for match in matches:
            date = match.get("date", "")
            if date not in sessions:
                sessions[date] = []
            sessions[date].append(match["id"])

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

        # --- Prediction streaks (consecutive days a player predicted) ---
        player_streaks = {}
        for player in players:
            current_streak = 0
            max_streak = 0
            for date in sorted_dates:
                match_ids = sessions[date]
                predicted = any(predictions.get(player, {}).get(mid) for mid in match_ids)
                if predicted:
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
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
        )
    except Exception as e:
        return f"Stats Error: {e}", 500


def update_kickoff_times():
    """Update kickoff times (IST) from official fixture sheet."""
    updates = [
        ("match_1", "June 12", "00:30"),
        ("match_2", "June 12", "07:30"),
        ("match_3", "June 13", "12:30"),
        ("match_4", "June 13", "06:30"),
        ("match_5", "June 14", "00:30"),
        ("match_6", "June 14", "03:30"),
        ("match_7", "June 14", "06:30"),
        ("match_8", "June 14", "09:30"),
        ("match_9", "June 14", "22:30"),
        ("match_10", "June 15", "01:30"),
        ("match_11", "June 15", "04:30"),
        ("match_12", "June 15", "07:30"),
        ("match_13", "June 15", "21:30"),
        ("match_14", "June 16", "00:30"),
        ("match_15", "June 16", "03:30"),
        ("match_16", "June 16", "06:30"),
        ("match_17", "June 17", "00:30"),
        ("match_18", "June 17", "03:30"),
        ("match_19", "June 17", "06:30"),
        ("match_20", "June 17", "09:30"),
        ("match_21", "June 17", "22:30"),
        ("match_22", "June 18", "01:30"),
        ("match_23", "June 18", "04:30"),
        ("match_24", "June 18", "07:30"),
        ("match_25", "June 18", "21:30"),
        ("match_26", "June 19", "00:30"),
        ("match_27", "June 19", "03:30"),
        ("match_28", "June 19", "06:30"),
        ("match_29", "June 20", "00:30"),
        ("match_30", "June 20", "03:30"),
        ("match_31", "June 20", "06:30"),
        ("match_32", "June 20", "09:30"),
        ("match_33", "June 20", "22:30"),
        ("match_34", "June 21", "01:30"),
        ("match_35", "June 21", "05:30"),
        ("match_36", "June 21", "09:30"),
        ("match_37", "June 21", "21:30"),
        ("match_38", "June 22", "00:30"),
        ("match_39", "June 22", "03:30"),
        ("match_40", "June 22", "06:00"),
        ("match_41", "June 22", "22:30"),
        ("match_42", "June 23", "02:30"),
        ("match_43", "June 23", "05:30"),
        ("match_44", "June 23", "08:30"),
        ("match_45", "June 23", "22:30"),
        ("match_46", "June 24", "00:30"),
        ("match_47", "June 24", "03:30"),
        ("match_48", "June 24", "06:30"),
    ]
    conn = get_db()
    cur = conn.cursor()
    for match_id, date, kickoff in updates:
        cur.execute("UPDATE matches SET date = %s, kickoff = %s WHERE id = %s", (date, kickoff, match_id))
    # Fix times to match actual teams in DB
    # DB has: match_22=Uzbekistan vs Colombia, match_23=England vs Croatia, match_24=Ghana vs Panama
    # Correct times: England=1:30AM, Ghana=4:30AM, Uzbekistan=7:30AM
    time_fixes = [
        ("match_22", "07:30"),  # Uzbekistan vs Colombia = 7:30 AM
        ("match_23", "01:30"),  # England vs Croatia = 1:30 AM
        ("match_24", "04:30"),  # Ghana vs Panama = 4:30 AM
    ]
    for match_id, kickoff in time_fixes:
        cur.execute("UPDATE matches SET kickoff = %s WHERE id = %s", (kickoff, match_id))
    conn.commit()
    conn.close()


# Initialize database on startup
init_db()
seed_matches()
update_kickoff_times()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
