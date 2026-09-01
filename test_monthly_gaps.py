"""Replicates run_monthly's gap detection to check the date maths."""
import re
from datetime import datetime, timedelta

def gaps_for(month_last_day, weekly_names):
    covered = set()
    for name in weekly_names:
        dates = re.findall(r"(\d{4}-\d{2}-\d{2})", name)
        if len(dates) == 2:
            day = datetime.strptime(dates[0], "%Y-%m-%d").date()
            end = datetime.strptime(dates[1], "%Y-%m-%d").date()
            while day <= end:
                covered.add(day); day += timedelta(days=1)
    last = datetime.strptime(month_last_day, "%Y-%m-%d").date()
    first = last.replace(day=1)
    gaps, run = [], []
    day = first
    while day <= last:
        if day in covered:
            if run: gaps.append((run[0], run[-1])); run = []
        else: run.append(day)
        day += timedelta(days=1)
    if run: gaps.append((run[0], run[-1]))
    return [(str(a), str(b)) for a, b in gaps]

ok = True
def check(got, want, msg):
    global ok
    good = got == want
    print(("  PASS  " if good else "  FAIL  ") + f"{msg}\n           got  {got}")
    if not good:
        print(f"           want {want}")
        ok = False

# The real August situation: one weekly, covering 17-23.
check(gaps_for("2026-08-31", ["YLL_Ops_Report_Weekly_2026-08-17_to_2026-08-23.docx"]),
      [("2026-08-01","2026-08-16"), ("2026-08-24","2026-08-31")],
      "August with only the 17-23 weekly -> two gaps")

# After we backfill the missing weekly, only the pre-pipeline gap remains.
check(gaps_for("2026-08-31", ["YLL_Ops_Report_Weekly_2026-08-17_to_2026-08-23.docx",
                              "YLL_Ops_Report_Weekly_2026-08-24_to_2026-08-30.docx"]),
      [("2026-08-01","2026-08-16"), ("2026-08-31","2026-08-31")],
      "with both weeklies -> only pre-pipeline days + the 31st")

check(gaps_for("2026-08-31", []), [("2026-08-01","2026-08-31")], "no weeklies -> whole month")
check(gaps_for("2026-09-30", ["YLL_Ops_Report_Weekly_2026-08-31_to_2026-09-06.docx"]),
      [("2026-09-07","2026-09-30")],
      "weekly spanning a month boundary counts its September days")
print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
raise SystemExit(0 if ok else 1)
