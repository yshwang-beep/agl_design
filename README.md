# Design Team Bot — weekly reports

Python standard-library runner for Slack reports. No Slack content, report drafts,
API responses or credentials are written to this public repository, logs or artifacts.
The runner fetches fresh source material in memory and uses OpenAI Responses with
`store: false`. Slack source text is sent to the OpenAI API for summarization.

## Setup status

Slack bot authentication, posting and channel/thread reading have been verified.
The weekly workflow is installed but scheduled posting stays disabled until
`REPORTS_ENABLED=true` is explicitly configured after migration verification.
Manual workflow runs are always draft validation only; they do not post.

Required repository Secrets:

- `SLACK_BOT_TOKEN`: installed Design Team Bot credential; do not put it in code.
- `OPENAI_API_KEY`: OpenAI API project credential. API usage has separate billing.

Optional repository Variables:

- `OPENAI_MODEL`: defaults to `gpt-4.1`.
- `REPORTS_ENABLED`: defaults off. Set `true` only after successful manual Monday
  and Friday draft runs and disabling the corresponding old cloud schedules.

Required repository Variables (enter actual internal IDs in settings, not source):
`SLACK_CHANNEL_ID`, `SLACK_BOT_USER_ID`, `SLACK_TEAM_ID`, `SLACK_GROUP_MENTION`,
`SLACK_WORKSPACE_URL` (the workspace's HTTPS Slack origin).

## Reporting

- Monday 09:00 Asia/Seoul: recent 14 days, current week open work, prior report
  sources followed up, previous Monday–Sunday explicit completions.
- Friday 17:00 Asia/Seoul: Monday–Friday relevant open work; completed work omitted.
- Both post a short introduction with the design group mention and one thread reply.
- The runner scans channel root metadata for fresh replies on old threads and
  reopens links from the four latest reports. Older items absent from all four
  reports and without new replies are not rediscovered as carry-over work.
- Previous reports locate source threads; their claims are not fresh evidence.
- Human report-thread corrections can serve as evidence. Attachments themselves
  are not downloaded or analyzed; important facts only in attachments require review.
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
