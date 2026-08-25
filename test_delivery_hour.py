"""Proves the 11:00/12:00 UTC cron pair lands on exactly one 7am ET run
per day, on both sides of the DST boundary."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
TZ = ZoneInfo("America/New_York")
ok = True
for label, day in [("EDT (Aug)", "2026-08-26"), ("EDT->EST switch (Nov 1)", "2026-11-01"),
                   ("EST (Nov 2)", "2026-11-02"), ("EST (Jan)", "2027-01-15"),
                   ("EST->EDT switch (Mar 14)", "2027-03-14"), ("EDT (Mar 15)", "2027-03-15")]:
    d = datetime.strptime(day, "%Y-%m-%d")
    hits = []
    for utc_hour in (11, 12):
        local = d.replace(hour=utc_hour, tzinfo=timezone.utc).astimezone(TZ)
        if local.hour == 7:
            hits.append(f"{utc_hour:02d}:00Z -> {local:%H:%M %Z}")
    good = len(hits) == 1
    ok = ok and good
    print(("  PASS  " if good else "  FAIL  ") + f"{label:<26} {day}: {hits or 'NO RUN'}")
print("\nRESULT:", "ALL PASS - exactly one 7am ET run every day" if ok else "FAILURES")
raise SystemExit(0 if ok else 1)
