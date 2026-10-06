# Connected Personal OS and graph

Personal OS views project authoritative SQLite/native state. They do not maintain browser-only copies of execution truth. Manual records capture intent; Plan with SPARKLE starts a normal authorized PersonalAgent execution and persists its source links.

## Persistent relationships

The personal graph stores owner-scoped nodes/edges in `personal_graph_nodes` and `personal_graph_edges`. It connects person, goal, task, project, learning plan/unit, skill, research, experiment, evidence, knowledge, document, decision, memory, plan, execution, step, agent, tool, result artifact and event entities. The latest 40 events per goal are projected with stable persisted IDs and timestamps; private event payloads remain outside graph nodes. Full event/trace history remains in its correlated tables and Activity surface.

| Source | Relationship | Target |
| --- | --- | --- |
| Person | owns | Goal |
| Event | describes | Goal |
| Goal | contains | Task |
| Goal | planned_by | Plan |
| Task / Plan | executed_by | TaskRun |
| Plan / TaskRun | contains / executes | Step |
| Step | uses / coordinated_by | Tool / Agent |
| Step | depends_on | Step |
| Step | produces | Result |
| Result | produces | Artifact |
| Project | supports | Original goal |
| Project / Research / Skill | executed_by | Latest bounded execution goal |
| Execution goal | part_of | Project or source goal/task |
| Learning | contains | Learning unit |
| Skill | developed_by | Learning plan |
| Assessment evidence | assesses | Learning unit |
| Experiment | investigates | Research |
| Experiment | produces | Evidence |
| Evidence | supports | Knowledge |
| Goal | proposes | Memory candidate |
| Persisted memory | supports | Knowledge or Decision |

Typed Result/Evidence states distinguish VERIFIED, UNVERIFIED, RECORDED and PERSISTED. An assessment records human-reviewed evidence; its existence is not proof of independent hardware performance. Experiment evidence retains the source verification state. Memory knowledge is projected only after native approval/reconciliation establishes PERSISTED state.

Projection is updated by execution persistence, manual record changes, learning creation/assessment, document persistence, experiment persistence and memory decisions. Reconciliation projects older records when an inspector first opens. Relationship changes clear obsolete owner-bound source edges in the same transaction as replacement; deletes remove corresponding graph references. Shared Person/Tool/Agent nodes do not carry one goal's deletion identity.

Foreign-owner targets cannot create relationships. Graph reads are bounded, omit raw result payloads and exclude edges whose endpoints are outside the returned view. The existing freshness/provenance WorldModel remains the digital/physical state service; the personal execution graph does not replace its observations or contradiction handling.

## User interface and API

| View | API / behavior |
| --- | --- |
| Conversation | Shared persisted sessions and ordinary planner execution |
| Tasks / Goals / Projects / Learning / Skills / Research | `/api/os`; manual records and linked planning |
| Knowledge | `/api/knowledge`, `/api/graph`; document/evidence/source relationships |
| Memory | `/api/memory`; owner-bound proposal/review/reconciliation |
| Execution | `/api/executions`, `/api/executions/<goal_id>`; steps, criteria, recovery, pause/resume/cancel/replan/retry |
| Approvals | Exact-scope persisted approval decision and original-goal resume |
| Automation | `/api/automations`; native persisted definitions plus policy-controlled conversation actions |
| Activity | `/api/activity`; correlated persisted execution events |
| System | `/api/system`; runtime diagnostics, model and connector health |

Read endpoints require the existing device conversation/task-status scopes. Execution controls also require task-status scope and ownership. Memory mutations require conversation and approval scopes. Approval and background endpoints enforce goal ownership. Views provide loading, empty, error and success states, escaped text, responsive navigation and explicit controls. Inspection dialogs expose verification evidence without private raw payloads.

The current Core is a private single-workspace deployment with scoped device enrollment. Gen-2 owner isolation is enforced for these records/views; inherited native stores and shared sessions do not constitute a new multi-tenant account service.

Completing one bounded execution leaves the source project's status and original goal relationship intact. It records `execution_goal_id` and `last_execution_status` separately. Users retain control over their larger goal/project completion.
