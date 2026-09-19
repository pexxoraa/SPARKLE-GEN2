# Daily Operating System

Gen-2 Daily OS is a persistent deterministic layer over bounded Personal Context, not a second task/project/scheduler system.

```text
bounded Personal Context
→ user-relevant filtering
→ urgency / importance / relevance ranking
→ persisted DailyBrief
→ PersonalAgent
→ user-approved disposition changes
→ unresolved carry-forward
```

A `DailyBrief` is scoped to one owner/day/context digest and contains provenance-bearing `DailyBriefItem` records. Generation is read/derived state and is idempotent: the same owner, day, bounded context, and processing version return the same brief identity. Internal lifecycle noise such as `goal_created` or `tool_observed` is not promoted as a user priority. User-relevant deadline/research/device/meeting activity may be included.

Items retain source/key, a bounded summary, deterministic score, action hint, state (`OPEN`, `DONE`, or `DISMISSED`), and source provenance. Closing a brief or changing an item disposition is approval-required; the approval binds the exact user, goal, tool, brief/item, and requested state. Model-supplied approval fields cannot create authority.

Unresolved `OPEN` items may carry into the next day's brief when they are not already represented by current context. `DONE` and `DISMISSED` items do not carry forward. Briefs and item states survive restart; persistence does not create personal memory or external side effects.

PersonalAgent exposes `daily_brief_generate`, `daily_brief_inspect`, `daily_brief_update`, and `daily_brief_close`. External actions arising from a brief still go through the existing goal/planning/permission/approval/execution/verification system. Scheduling a recurring morning/weekly brief continues to use the existing automation orchestration rather than another scheduler.
