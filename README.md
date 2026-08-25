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

## Vikunja task sync (Daily only)

After the Daily report is built, `vikunja_sync.py` pushes its action items
onto the Kanban board at https://tasks.yulelovelights.com, in the project
**Tasks from Reports**. It consumes the same structured `report` dict the
docx renderer uses — the finished Word document is never parsed.

Weekly and Monthly reports do **not** sync; they would just restate items
that are already on the board.

### What it does with each action item

| Situation | What happens |
|---|---|
| New work | Task created, dropped in the owner's bucket, assigned, labelled `auto` |
| Same item, same wording as an existing open task | No new task — a comment is added to the existing one |
| Same work, reworded ("call the HOA back" → "follow up with Palm Beach HOA") | No new task — Claude matches it to the open task and comments on it |
| Report says it's already done | Existing task moved to **Auto Closed** (never marked Done — you confirm and move it to Done yourself) |
| Vague, garbled, or non-actionable | Not written to the board; listed in the DM as "NOT added" so nothing is silently lost |

Owner → bucket: `Jason` → For Jason, `Naldo` → For Naldo, `Both` and
`TJ_Social` → For Anyone. `Both` is assigned to both of you; TJ has no
Vikunja account, so his items land unassigned in For Anyone.

Everything that happened is appended to the daily Discord DM, so the board
never changes without you seeing exactly what changed.

### Required buckets

The kanban view must have buckets titled exactly **For Jason**, **For
Naldo**, **For Anyone**, and **Auto Closed** (a **Done** bucket is expected
too, but the sync never writes to it). A missing bucket fails loudly with
the names it couldn't find rather than guessing.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `VIKUNJA_API_TOKEN` | yes | — | Vikunja → Settings → API Tokens. Needs read+write on tasks, labels, comments, and read on projects. |
| `VIKUNJA_USERNAME_JASON` | yes | — | Vikunja username to assign Jason's items to |
| `VIKUNJA_USERNAME_NALDO` | yes | — | Vikunja username to assign Naldo's items to |
| `VIKUNJA_BASE_URL` | no | `https://tasks.yulelovelights.com` | Instance URL |
| `VIKUNJA_PROJECT_NAME` | no | `Tasks from Reports` | Project title to sync into |
| `VIKUNJA_SYNC_ENABLED` | no | `true` | Set `false` to turn the sync off without touching code |
| `VIKUNJA_SYNC_DRY_RUN` | no | `false` | Plan and report, write nothing. Run this way for the first week. |
| `VIKUNJA_SYNC_MAX_NEW_TASKS` | no | `15` | Ceiling on new tasks per day — a bad extraction can't flood the board |
| `VIKUNJA_SYNC_MODEL` | no | `claude-opus-5` | Model used for the dedup/matching pass |
| `VIKUNJA_SYNC_FORCE` | no | `false` | Re-sync a date that's already been synced |

### Safety properties

- **Nothing is written twice.** A date that fully synced is skipped on a
  rerun, and each auto-created task carries a `yll-sync-id` fingerprint in
  its description, so duplicates are caught even if the Drive index file is
  lost. The index lives at `vikunja_task_index.json` in the internal-state
  folder.
- **A board failure never blocks the report.** The sync is wrapped in
  `main.py`; if it throws, the daily report still goes out and the DM says
  the sync failed.
- **Everything auto-created is labelled `auto`** — filter by that label to
  bulk-review or bulk-delete a bad run.
- **The sync never marks anything Done.** Only you do that.

### Testing it

Offline — no API key, no network, nothing touched:

```
python test_vikunja_sync.py
```

Against the real board, replaying a past day's saved report (set
`VIKUNJA_SYNC_DRY_RUN=true` first so it only reports what it *would* do —
dry runs are never recorded, so you can replay the same day repeatedly):

```
python vikunja_sync.py 2026-08-24
```

## Cost control

- Check usage anytime at https://console.anthropic.com under **Usage**.
- If costs run higher than expected, the biggest lever is the source text
  volume — the live chatter transcripts can be verbose. Trimming what
  counts as "source text" (e.g. skipping the live word-by-word feed and
  only using Scripty's compiled summaries, which the capture bot already
  does) keeps this efficient.
