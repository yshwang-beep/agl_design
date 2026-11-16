# Friday dashboard report

Friday reports use saved dashboard tasks, including human edits. They do not
re-extract or reinterpret Slack, call OpenAI, or write to the dashboard.

- Schedule: Friday 17:00 Asia/Seoul, early readiness at 16:30 and a 17:00 backup.
- Switch and destination: existing FRIDAY_REPORTS_ENABLED and SLACK_CHANNEL_ID.
- Execution: design-board.yml, preserving the existing OIDC identity. No new
  workflow identity, server permission or credential is introduced.
- Source: authenticated read-only snapshot from the workboard. Display both
  query time and source cutoff. Stop if the cutoff is missing or outside the
  current week. This does not collect new Friday-afternoon Slack evidence.
- Completion totals require an explicit completedDate in the report week.
  Missing completion dates remain visible without being counted as weekly wins.
- Server activeTasks preserves reviewed identity and manual ownership/status.
  Include current tasks and archived tasks explicitly completed this week.
- Follow-up actions without next-week deadlines are marked unconfirmed; never
  invent a next-week commitment or a delay's cause/impact.
- Parent: summary, blockers and next actions; thread: every selected task with
  status, owner, deadline, issue, next action, decision and source link.
- Manual phase friday_preview validates without posting and logs no source data.
- Scheduled writes are limited to Friday 17:00–19:00 KST. Existing reports prevent
  duplicates, including reports produced by the old Slack-based workflow.
- Legacy Friday schedules are removed from design-weekly.yml in the same change.
  Monday reporting/corrections and daily dashboard collection keep their gates.

Offline validation: python3 -m unittest test_dashboard_report.py
test_weekly_report.py test_report_accuracy.py test_board_weekly.py test_daily_board.py

For an authorized private local export, set DASHBOARD_SNAPSHOT_FILE,
DASHBOARD_PREVIEW_FILE and WORKBOARD_URL and run dashboard_report.py. This mode
cannot be used by a publishing scheduler. Never commit real snapshot or preview
contents to this public repository.
