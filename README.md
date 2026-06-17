# ⚽ World Cup 2026 Prediction Contest

A simple web app for your WhatsApp group to predict World Cup match winners and scorers.

## Scoring
- Winner correct = 1 point
- Scorer correct = 1 point  
- Both correct = 3 points

## Run Locally

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

## Deploy to Render (Free)

1. Push this folder to a GitHub repo (personal account)
2. Go to https://render.com → sign up with GitHub
3. Click "New" → "Web Service" → connect your repo
4. Settings auto-detected from `render.yaml`
5. Click Deploy → get your public URL
6. Share the URL in your WhatsApp group!

## How to Use

### Admin (you):
1. Go to `/admin`
2. Add all group members as players
3. Add upcoming matches
4. After each match, enter the result (winner + first scorer)

### Players (group members):
1. Open the shared link
2. Click "Make Predictions"
3. Select their name, predict winner + scorer for each match
4. Leaderboard updates automatically after results are entered
