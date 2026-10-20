# Monday workboard automation

This workflow collects channel evidence, validates a weekly draft, preserves the
previous board period, updates the authenticated Cloudflare workboard, and only
then schedules one Slack notice for Monday 09:00 Asia/Seoul.

## Schedule and gates

- Collection starts Monday 07:30 KST (Sunday 22:30 UTC).
- Sources cover the preceding Monday 09:00 through Sunday 23:59:59 KST.
- Board writes stop at Monday 08:30 KST. A late or incomplete run fails closed.
- A verified update may schedule the 09:00 notice until 08:58 KST.
- GitHub `BOARD_ENABLED=true` and Cloudflare `AUTOMATION_ENABLED=true` are both
  required for production writes. Keep both false until real-source validation.
- GitHub scheduling can be delayed. Slack's accepted scheduling receipt, rather
  than GitHub's start time, establishes the intended delivery time.
- Manual runs never change the board or send/schedule Slack messages.

The workflow is separate from the Friday report. Its source and destination
settings do not replace the Friday channel configuration.

## Private configuration

Repository Secrets: `BOARD_CONFIG`, `SLACK_USER_TOKEN`, `SLACK_BOT_TOKEN`,
`OPENAI_API_KEY`, and optional `REPORT_POLICY`. Repository variable:
`WORKBOARD_URL`, containing only the workboard HTTPS origin. `BOARD_CONFIG`
contains the workspace identity, eight designers, channel IDs, mention group,
collaborators, exclusions, and collection policy. Keep this configuration private.

The user token needs public-channel read/history scopes. Collection enumerates
public channels and explicitly checks channel types; personal and group DMs are
never sources. The bot token handles the notice, delivery-channel readback, and
scheduled-message deduplication. No credentials or company snapshots belong in
this repository, logs, artifacts, or caches.

Cloudflare verifies a short-lived GitHub OIDC token for this repository's numeric
identity, owner, main branch, and exact workflow file. Manual tokens may only read
the automation snapshot/status. No administrator password or permanent workboard
integration token is stored in GitHub.

## Preservation and retries

The server atomically preserves the previous active period and creates new rows.
Older archived rows are immutable. Human-edited values remain intact, with AI
suggestions stored separately. Unfinished tasks carry forward; missing new source
evidence is marked for confirmation. Snapshot revision conflicts stop the write.

The server records the notice intent before Slack is called, then records its
accepted scheduling ID or uncertain/rejected outcome. An uncertain response must
be reconciled with Slack; it must never trigger another automatic send. A later
scheduled execution may complete a missing notice for an already committed period
using its authenticated execution identity. It does not rewrite that period.

`workflow_dispatch` defaults to `preflight`: authenticated board/status reads and
bot/delivery-channel reads only, without source collection or AI calls.
`validate` additionally collects actual sources and validates the draft, still
without board or Slack writes. Do not enable production until both succeed.

Local checks: `python3 -m unittest test_board_weekly.py test_weekly_report.py`.
