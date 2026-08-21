# YLL Report Generator

Runs once a day (via Railway Cron Schedule). Always attempts a Daily
report; on Mondays also builds the Weekly rollup; on the 1st of the month
also builds the Monthly rollup. Fully cloud-hosted — no computer needs to
stay on.

## What it needs, and where to get each piece

### 1. Anthropic API key
1. Go to https://console.anthropic.com and sign in (create an account if
   you don't have one — separate from your claude.ai login).
2. Add a payment method under **Settings -> Billing**. This is pay-as-you-go,
   not a subscription — for this volume of usage, expect a small monthly
   cost, but check current pricing at https://www.anthropic.com/pricing
   rather than take a number from me, since pricing can change.
3. Go to **API Keys -> Create Key**. Copy it immediately — this is
   `ANTHROPIC_API_KEY`.

### 2. Google Drive folder IDs (four total)
You already have the Shared Drive with raw transcripts from Part 1 —
that's `GOOGLE_TRANSCRIPTS_FOLDER_ID` (reuse the same ID).

Create three more folders inside your Shared Drive:
- **"YLL Ops Reports - Weekly"** -> copy its ID -> `GOOGLE_WEEKLY_REPORTS_FOLDER_ID`
- **"YLL Ops Reports - Monthly"** -> copy its ID -> `GOOGLE_MONTHLY_REPORTS_FOLDER_ID`
- **"_internal_state"** -> copy its ID -> `GOOGLE_INTERNAL_STATE_FOLDER_ID`
  — this one is pipeline plumbing, not a deliverable. It holds each daily
  report's structured data so Weekly can build on it. No reason for you
  or Jason to open it, but don't delete it either.

Since these live inside the same Shared Drive as the transcripts folder,
the service account already has access — no extra sharing step needed.

### 3. Discord user IDs (for DMs)
1. In Discord, make sure Developer Mode is on (already done from Part 1).
2. Right-click Naldo's name/profile anywhere in the server -> **Copy User ID**
   -> `NALDO_DISCORD_USER_ID`.
3. Same for Jason -> `JASON_DISCORD_USER_ID`.
4. The bot needs to already share a server with both of you to DM you —
   it does, since it's in Yule Love Lights already.

### 4. Reuse from Part 1
`DISCORD_BOT_TOKEN` and `GOOGLE_SERVICE_ACCOUNT_JSON` — same values as the
capture bot, no changes needed.

## Deploying

This is a **separate Railway service** from the capture bot (different
language, different job — one's an always-on listener, this one runs
once a day and exits).

1. Push this folder to a new GitHub repo (or a new folder in the same
   repo as the capture bot — either works).
2. In Railway, **New -> GitHub Repo**, pick it.
3. Railway should detect Python. If it doesn't auto-set the start command,
   set it manually: Settings -> Deploy -> Custom Start Command ->
   `python main.py`
4. Add all 7 environment variables listed above in the Variables tab.
5. Go to Settings -> Deploy -> **Cron Schedule**. Set it to:
   ```
   0 11 * * *
   ```
   This means 11:00 UTC daily, which is 7:00 AM Eastern **during Daylight
   Saving Time (roughly March-November)**. When clocks fall back in
   November, change this to `0 12 * * *` to stay at 7am Eastern — Railway's
   cron runs in UTC and won't auto-adjust for DST. Worth a calendar
   reminder twice a year, or check Railway's cron settings for a timezone
   option if one's been added since — I'd verify current behavior in the
   app rather than take my word for it.
6. Deploy. A cron-scheduled service won't show "Active" the way the
   capture bot does — it runs, does its work, and exits, then Railway
   spins it up again at the next scheduled time. Check **Deploy Logs**
   after the first scheduled run for `Daily report ... generated and sent`
   (or the skip message if there were no calls).

## Testing before the first real scheduled run

Don't wait for 7am tomorrow to find out if it works. In Railway's console
(same place you ran `node backfill.js` before), run:

```
python main.py
```

This runs it immediately with today's date. Since "yesterday" needs real
transcripts to exist, this is most useful for catching setup errors
(missing env vars, folder ID typos, bad credentials) rather than seeing a
real report — but if yesterday had real calls, you'll get a real Discord
DM out of it.

## Cost control

- Check usage anytime at https://console.anthropic.com under **Usage**.
- If costs run higher than expected, the biggest lever is the source text
  volume — the live chatter transcripts can be verbose. Trimming what
  counts as "source text" (e.g. skipping the live word-by-word feed and
  only using Scripty's compiled summaries, which the capture bot already
  does) keeps this efficient.
