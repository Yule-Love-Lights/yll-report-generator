# Yule Love Lights — Automated Ops Reporting

## Purpose of this project

Naldo and Jason run Yule Love Lights (YLL) and talk on the phone nearly
every working day. A Discord bot ("Scripty Transcriptions") transcribes
those calls and posts a compiled `.txt` transcript in the `#transcript`
channel after each session. A separate capture bot watches that channel
and archives every transcript into a Google Drive Shared Drive
("YLL Transcripts"), named by date and time
(`YYYY-MM-DD_HHMM_transcript.txt`).

This project turns those transcripts into three recurring reports —
**Daily, Weekly, and Monthly** — automatically, with no manual upload or
request needed. This is a running pipeline, not a one-off chat task.

## Who's who (speaker mapping)

The Discord bot labels speakers inconsistently — use context, not just the
label, to identify who's talking.

- **`naldovens`** → **Naldo**, founder/President of Holiday Cheer. Talks in
  first person about installs, sales calls, the van, the warehouse, etc.
- **`Jason`** → **Jason**, office manager and Naldo's right hand. Handles
  quotes, customer texts/calls, GoHighLevel, admin.
- **TJ**, social media — Discord handle **`d0_pe`**. **Refer to TJ as
  he/him.** The transcription bot has mislabeled him inconsistently in the
  past (e.g. as `niar`) — identify him by context (social media, content
  calendars, Instagram/Facebook, editing, "Marco Garcia" reference, etc.),
  not by trusting the speaker tag.
- Other names that may come up: **Kelly** (US-based office assistant), **K /
  Kim & Ann** (Philippines-based, quotes/comms), **James** (lead
  installer), **Little James**, **Sun Sun** (installers), **David** (former
  crew lead, may return), **warehouse person** (inventory).

If a new recurring name shows up, note it and carry it forward across
reports.

## Known data quality issues

These transcripts are auto-generated and often heavily degraded:

- Long stretches of on-site noise, cross-talk, and background chatter get
  transcribed as filler ("thank you," repeated fragments, gibberish).
- Speaker labels are sometimes wrong, especially for third parties.
- Real content is often sparse and scattered between noise — it takes a
  full read, not a skim, to find it.

Never fabricate or infer an action item that isn't actually supported by
readable text. If something feels like it should be there but isn't
findable, say so rather than guessing. Flag garbled numbers/dates as
low-confidence rather than guessing at the real value.

## Report cadence and rollup logic

Each report builds on the one before it — don't re-derive everything from
raw transcripts every time.

- **Daily**: built directly from that day's transcript file(s) in the
  Shared Drive. **If a given day has zero transcript files, skip it — do
  not generate an empty daily report.**
- **Weekly**: built by rolling up that week's daily reports (Monday
  through Sunday). Delivered the following **Monday morning**, so the
  team sees last week's report at the start of the new work week.
- **Monthly**: built by rolling up that month's weekly reports.

## What every report must contain

1. **Master Action List (open items)**, grouped by owner (Naldo / Jason /
   Both / TJ-Social), each item tagged with the date it was raised.
2. **Aging flag on open items** — for Weekly and Monthly reports, note how
   long each open item has been outstanding (e.g. "van build-out — open
   4 weeks running"). This is the single most useful addition: it surfaces
   what keeps getting talked about but never resolved.
3. **Closed since last report** — a short section listing what closed out
   since the previous report of that same cadence, so progress is visible,
   not just a growing backlog.
4. **Notable numbers** — a dedicated callout for dollar figures, pricing
   changes, quote values, and revenue pacing mentioned in the period.
   Don't let these get buried in prose.
5. **Decisions / notes** — anything decided, changed, or committed to,
   even if it isn't a discrete action item (e.g. new pricing, a staffing
   decision, a process change).
6. **Important conversations to have** — flagged directly, not softened.
   Naldo wants avoidance patterns (a stalled conversation, a recurring
   drag like the van build-out) named plainly, not buried in a polished
   summary.
7. **Day-by-day detail** (Daily and Weekly reports only — Monthly stays at
   the rollup/summary level, no day-by-day breakdown) — chronological,
   "Action items" and "Decisions / notes" per day, with a dedicated
   sub-heading for any distinct meeting (e.g. a TJ content-strategy call).

## Format

- **Word document (.docx)** for all three cadences — do not switch to PDF.
- Use **real interactive Word checkboxes** (Content Control checkboxes),
  not Unicode "☐" glyphs — those don't actually toggle when clicked.
- Title block: company name, report type (Daily/Weekly/Monthly), date
  range covered, number of sessions.
- Short data-quality callout near the top (see "Known data quality
  issues" above).

## File naming (ISO dates, sorts correctly)

- Daily: `YLL_Ops_Report_Daily_YYYY-MM-DD.docx`
- Weekly: `YLL_Ops_Report_Weekly_YYYY-MM-DD_to_YYYY-MM-DD.docx` (Monday
  date to Sunday date)
- Monthly: `YLL_Ops_Report_Monthly_YYYY-MM.docx`

## Storage

- **Weekly and Monthly reports** are saved to Google Drive for long-term
  reference. Naldo and Jason both have edit access.
- **Daily reports are NOT saved to Drive** — generated and delivered, but
  not archived, to avoid clutter. (Daily still needs to exist as an
  artifact for delivery even though it isn't stored long-term.)

## What NOT to assume

- Don't invent numbers, names, or decisions that aren't actually stated in
  the transcript text.
- Pricing, staffing, and roadmap details may change week to week — if a
  new transcript contradicts a previous report (e.g. a new price, a
  staffing change), treat the newer transcript as the current source of
  truth and flag the change explicitly rather than silently overriding
  prior reports.

## Tone

Match Naldo's house style: direct, no fluff, bullet points over
paragraphs, executive-summary framing. Call out avoidance patterns or
recurring problems plainly (e.g. the van build-out) rather than softening
them.
