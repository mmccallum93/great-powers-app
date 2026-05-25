# Great Powers Game — Briefing for Claude

## Who this is for

Matt McCallum, a teacher, built this for his social studies class. He is not a developer — communicate in plain English. Everything must work entirely in the browser. Bat files are only for deployment.

## What this project is

A classroom web game where student teams build countries by spending economic points on armies, navies, industries, and colonies. One teacher control panel manages turns and war resolution.

- `/`         — Public leaderboard + country tabs (index.html)
- `/teacher`  — Teacher control panel (teacher.html)

## Deployment

- **GitHub**: `mmccallum93/great-powers-app` (private)
- **Production URL**: set after first deploy
- **Deploy**: double-click `Update Cloud Dashboard.bat` (git push + vercel deploy --prod)
- `.vercel/project.json` links this folder to the Vercel project (gitignored)

## Stack

Flask · Werkzeug · requests · Vercel (@vercel/python, @vercel/static)

`requirements.txt`: flask, werkzeug, requests — nothing else. No Vercel Blob SDK.

## Data storage — Vercel Blob (private store)

All game data lives in one blob: `game/state.json`.

Store: created when the Vercel Blob store is linked to the project. Token format: `vercel_blob_rw_{storeId}_{rest}` — the store ID is extracted from the token, so no separate BLOB_BASE_URL is needed.

### Blob REST API (direct HTTP — no SDK)

| Operation | Method + URL | Notes |
|-----------|-------------|-------|
| Write | PUT `https://vercel.com/api/blob?pathname={path}` | headers: x-vercel-blob-access:private, x-allow-overwrite:1 |
| Read  | GET `https://{storeId}.private.blob.vercel-storage.com/{path}` | Authorization: Bearer {token} |

All calls require `Authorization: Bearer {token}` and `x-api-version: 11`.

### BLOB_READ_WRITE_TOKEN setup
When setting via CLI, avoid PowerShell piping (adds BOM):
```
cmd /c "vercel env add BLOB_READ_WRITE_TOKEN production < _clean_token.txt"
```

## Auth

No HTTP Basic Auth. Each request sends password in the JSON body (stored in browser sessionStorage). Passwords are hashed with werkzeug.security.generate_password_hash.

## Game state structure

Stored as `game/state.json` in Vercel Blob:
```json
{
  "initialized": true,
  "year": 1900,
  "phase": "purchase",
  "teacher_password_hash": "...",
  "countries": [
    {
      "id": "russia", "name": "Russia", "color": "#c0392b",
      "army": 2, "navy": 1, "industry": 2, "colonies": 2,
      "password_hash": "...",
      "purchases_submitted": false,
      "pending_purchase": null
    }
  ],
  "pending_wars": []
}
```

## Key formulas

- Econ Points = industry + colonies
- Military Power = army + navy / 2
- Victory Points = Econ Points + Military Power
- Industry cost: 2 pts each (max 500 total)
- Army/Navy cost: 1 pt each (military only, not permanent)
- Colony cost: 1 pt each (need 1 navy per 2 colonies)

## War casualty table

| Die Roll | Winner loses (army/navy) | Loser loses (army/navy + colonies) |
|----------|--------------------------|-------------------------------------|
| 1 | 50% | 70% |
| 2 | 40% | 60% |
| 3 | 30% | 50% |
| 4 | 20% | 40% |
| 5 | 10% | 30% |
| 6 | 0%  | 20% |

Industries are NEVER lost in war.

## File map

| File | Purpose |
|------|---------|
| `api/index.py` | Flask app — all routes, blob storage, game logic |
| `templates/index.html` | Public leaderboard + country tabs |
| `templates/teacher.html` | Teacher control panel |
| `Update Cloud Dashboard.bat` | git push + vercel deploy --prod |
