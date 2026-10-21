# Design Team Bot — weekly reports

Python standard-library runner for Slack reports. No Slack content, report drafts,
API responses or credentials are written to this public repository, logs or artifacts.
The runner fetches fresh source material in memory and uses OpenAI Responses with
`store: false`. Slack source text is sent to the OpenAI API for summarization.

## Setup status

Slack bot authentication, posting and channel/thread reading have been verified.
The weekly workflow has separate Monday and Friday publication switches, both off
by default. Each schedule stays disabled until its own switch is explicitly set
to `true` after verification of that report.
Manual workflow runs are always draft validation only; they do not post.

Required repository Secrets:

- `SLACK_BOT_TOKEN`: installed Design Team Bot credential; do not put it in code.
- `OPENAI_API_KEY`: OpenAI API project credential. API usage has separate billing.
- `REPORT_POLICY`: private confirmed task corrections. Required so a missing
  migration policy cannot silently reopen closed work. Keep this in Secrets,
  not Variables: ordinary step environment values appear in public Actions logs.

Optional repository Variables:

- `OPENAI_MODEL`: defaults to `gpt-4.1`.
- `FRIDAY_REPORTS_ENABLED`: defaults off. Set `true` only after a successful manual
  Friday draft run and disabling the corresponding old Friday cloud schedule.
- `MONDAY_REPORTS_ENABLED`: defaults off. Set `true` only after a successful manual
  Monday draft run and disabling the corresponding old Monday cloud schedule.
  Enabling Friday does not enable Monday. The former `REPORTS_ENABLED` variable
  is no longer used.
- `SLACK_CHANNEL_NAME`: optional display name; without it Slack's channel mention
  renders the configured channel. Do not hardcode workspace names in source.

Required repository Variables (enter actual internal IDs in settings, not source):
`SLACK_CHANNEL_ID`, `SLACK_BOT_USER_ID`, `SLACK_TEAM_ID`,
`SLACK_WORKSPACE_URL` (the workspace's HTTPS Slack origin).
`SLACK_GROUP_MENTION` is optional and contains the shared Slack group/user mention
tokens for both Monday and Friday parent intros and the workboard notice.

## Reporting

- Monday 09:00 Asia/Seoul: recent 14 days, current week open work, prior report
  sources followed up, previous Monday–Sunday explicit completions.
- Friday 17:00 Asia/Seoul: current-week relevant open work, including weekend
  deadlines, and explicitly completed Monday–Friday work in the fourth section.
- Both post a short introduction and one thread reply. Configured group/user
  mentions appear once in the parent introduction.
- Friday parent intros also include a short thank-you/weekend encouragement.
  Six approved variants rotate by report week; retries retain the same wording.
  The rotation starts with the approved message on 2026-10-23 and repeats after
  six weeks. Monday intros and workboard notices do not add this Friday greeting.
- Monday parent intros use a separate set of six start-of-week greetings,
  beginning with the first approved message on 2026-10-26. They rotate weekly,
  repeat after six weeks and remain identical on retries of the same report.
- A manual validation uses the most recent already elapsed nominal report time,
  so a Friday check on Tuesday tests the previous Friday's full reporting period.
- The runner scans channel root metadata for fresh replies on old threads and
  reopens original source links from every accessible prior report. There is no
  fixed four-report carry-over limit. Inaccessible carried sources stop the run.
- This runner rescans Slack; it does not migrate or update the former private
  ChatGPT Page's incremental checkpoint, cached drafts or delivery state. Old work
  never linked by a report and without recent activity can remain undiscovered.
  Do not describe this as a migration of that private cache.
- Previous reports locate source threads; their claims are not fresh evidence.
- Human report-thread corrections can serve as evidence. Attachments themselves
  are not downloaded or analyzed; important facts only in attachments require review.
- Role choices are restricted to users present in source data. A role absent from
  its cited original message becomes `확인 필요`; no substitute person is inferred.
- Completed rows require positive completion wording, a real cited source, an
  explicit date expression in that source and the correct Monday/Friday date
  window. Deadlines, negative completion wording and pending approval fail closed.
- Only the designated channel is read. Notion board updates, personal briefings
  and ChatGPT Page state synchronization are outside this workflow.

## Reliability

GitHub scheduled runs can be delayed; this is not an exact-time SLA. Posting is
allowed only within two hours of the nominal time on the correct day. Missed
windows fail closed. No recurring catch-up or automatic cross-day posting.

Both draft messages are built and validated before the parent is posted. Existing
reports are detected from their date and title or bot metadata. An existing complete
pair is skipped; a parent-only report gets a reply. After posting the thread is read
back. A reply is retried once only when a successful read confirms it is absent.
An ambiguous write is not automatically retried. Check Slack before rerunning.

The repository concurrency group serializes runs of this workflow only. It cannot
serialize old ChatGPT schedules; disable those before enabling GitHub posting.

The runner has a 240,000-character source input cap, a 30,000-root pagination cap,
a 10,000-token model output cap and a 5,000-character detail cap. Exceeding any
cap stops the report instead of silently truncating it. Long history can require
separate private checkpoint storage before activating production scheduling.

Run offline checks: `python3 -m unittest test_weekly_report.py`.
