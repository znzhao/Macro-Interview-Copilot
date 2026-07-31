# UI Specification

Page-by-page behavior, shared components, and Streamlit runtime discipline.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [AI_SPEC.md](AI_SPEC.md)

> **Pages are UI only.** No SQL, no prompt text, no scoring arithmetic. Every bullet below maps to an engine or repository call ([ARCHITECTURE §2](ARCHITECTURE.md#2-layer-rules)).

---

# 0. Navigation

`st.navigation` with labelled groups. Flat lists stopped scaling once both banks, the agent, and the inbox arrived.

```
PRACTICE          Dashboard · Interview · Review · Progress
LIBRARY           Questions · Knowledge
CREATE            Author · My Drafts
ACCOUNT           Inbox (3) · Settings · Admin
```

Two rules that keep this from sprawling again:

1. **Tier is a tab, never a page.** Questions and Knowledge each carry `Verified | Community | Mine` tabs. Three pages per bank would triple the filter, card, and search code and make the sidebar unusable.
2. **Phase-gated items are hidden, not disabled.** Interview, Review, and Progress simply do not appear until Phase 3/4 ships. A greyed-out nav item is a promise you have to keep on someone else's schedule.

The Inbox item carries an unread count badge, driven by a single indexed `COUNT(*) WHERE read_at IS NULL` ([DATA_SPEC §5.9](DATA_SPEC.md#59-notifications)) cached for 30 seconds — it runs on every page load.

---

# 1. Pages

## 1.1 Dashboard — `dashboard.py`

- Questions attempted, sessions completed, rolling 30-day average total score.
- Five-dimension radar of current mastery (`score_radar`).
- **Three weakest topics**, each with a one-click "drill this" that opens a focused session.
- Recent sessions with scores; resume any session still `active`.
- Practice-frequency sparkline.

**Empty state matters more than the populated state here.** A brand-new user must see an onboarding card — set target roles → add an API key → start your first interview — not four zeroed charts. Zeroed charts read as a broken app.

## 1.2 Questions — `questions.py`

Tabs: **Verified · Community · Mine**. Same search, filters, and cards throughout — only the tier predicate changes.

- Search box ([CONTENT_SPEC §5.1](CONTENT_SPEC.md#51-level-1--full-text-v1)) plus filter sidebar. **`verification_level` is a top-level filter, not buried** — since [D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance) removed the source requirement, it is how a user finds genuinely-sourced material.
- Cards: text, module/topic, difficulty, institutions, **verification badge**, source link, vote (±1) with net score, favorite, report, comment count.
- Expand for: the **answer key** (§1.2.1), notes (autosaved), seed follow-ups, your attempt history, and the comment thread.
- "Practice this" and "Add to session" (Phase 3).
- On the **Mine** tab: tier controls — *Share with the community*, *Submit for verified review*, *Return to private* — plus edit and delete.

### 1.2.1 Rendering an answer key

Five collapsible sections of bullets ([D10](DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose)), each labelled with the rubric dimension it prepares, collapsed by default.

- **Never rendered during an active interview turn.** The component takes an explicit `allow_reveal` argument that the Interview page passes as `False`; it is not a styling decision a future page can forget.
- Editing is per-section, with the 8-bullet / 240-character limits shown as live counters rather than enforced by a rejection after the user has typed.
- Absent keys show *"No answer key yet"* with an "Ask the agent to draft one" action, not an empty box.

## 1.2b Knowledge — `knowledge.py`

Same three tabs, same governance controls, same card grammar as Questions — deliberately, so the second bank costs a user nothing to learn.

- Browse by module and topic, search over title/summary/body, render Markdown.
- Card: title, summary, modules/topics, **verification badge**, vote, comment count, token estimate.
- Detail view: rendered Markdown, related documents from `related_slugs`, "Related questions" filtered by shared modules/topics, comment thread.
- **Mine** tab: *Upload Markdown*, *Draft with AI*, plus the same share/submit/private controls.
- Archived documents render with an "archived" notice rather than 404-ing — stored `suggested_readings` slugs must always resolve ([CONTENT_SPEC §7.3](CONTENT_SPEC.md#73-slugs-are-permanent)).

## 1.2c Author — `author.py`

The agentic authoring page ([AI_SPEC §6](AI_SPEC.md#6-authoring-agent)). Two panes.

**Left — configure and ground.** Module, topic, difficulty, target role, optional institution. Grounding: knowledge picker with a **live token budget meter** against the 8,000-token cap, a URL box, and an uploader (`.md`/`.txt`, ≤1 MB, ≤3).

**Right — the draft.** The full question and answer key, always complete and always editable inline. Below it: a feedback box, and `Regenerate` · `Save to my bank` · `Share with community`.

Non-negotiables:

- **The one-click path must stay one click.** Module + topic + Generate, with everything else collapsed. Most users will never open the grounding pane, and the page must not imply they should.
- **Manual edits win.** Text the user changed is what goes into the next refinement turn — the model must never silently revert a correction.
- **Nothing auto-saves.** No draft touches the database until Save or Share.
- `st.status` narrates every tool call live — *"Reading imf.org…"*, *"Searching your knowledge bank…"*. A silent 40-second agent loop reads as a hung app.
- Cap exhaustion renders as a labelled incomplete draft with a `Continue` action, never as an error.
- No API key → the page explains and links to Settings **before** the user configures anything, not after they press Generate.

## 1.2d My Drafts — `drafts.py`

Private bank plus submission status in one place: private questions and documents, pending review requests with their submitted date, and decided ones with the admin's note. This is where "what happened to the thing I submitted?" gets answered without hunting through the Inbox.

## 1.2e Inbox — `inbox.py`

Reverse-chronological notifications ([D15](DECISIONS.md#d15--in-app-notifications-only-no-email)): submission approved, submission rejected (with the admin's reason), comment on your content, reply to your comment. Each deep-links to its target and marks read on open, with a *Mark all read*.

Empty state says *"No notifications"* — not a zeroed dashboard.

## 1.3 Interview — `interview.py`

- **Config step:** mode, institution, length, modules, adaptive toggle.
- **Turn view:** one question, answer textarea, elapsed timer, submit.
- **After submit:** rubric breakdown, strengths and gaps, then either a follow-up or the next question.
- "End early" marks the session `completed` with the turns scored so far — never `abandoned` silently.
- If no API key is set, warn clearly up front with a link to Settings rather than failing at submit time after the user has typed five paragraphs.

State machine: [AI_SPEC §4.2](AI_SPEC.md#42-session-state-machine). The page renders states; it does not implement transitions.

Additionally: **answer keys are never revealed during an active turn.** `answer_key_view` is called with `allow_reveal=False`; the key becomes visible on the Review page after the answer is scored, where comparing your reasoning against the key is the point.

## 1.4 Review — `review.py`

- Session list → turn-by-turn drill-down.
- Per turn: the question as asked, your answer, five dimension scores with justifications, gaps, improved outline, suggested readings (linked into the Knowledge page).
- Session-level coaching synthesis (`coach.v1`).
- **"Retry this question"** starts a fresh single-question attempt and shows the delta against your prior score — the most directly motivating interaction in the product.

## 1.5 Knowledge

Moved to §1.2b — it is a governed bank now, not a reference viewer ([D12](DECISIONS.md#d12--the-knowledge-base-is-a-three-tier-postgres-bank)).

## 1.6 Progress — `progress.py`

- Total score trend over time.
- **Per-dimension trends** — the most actionable view in the app. Someone plateauing overall is usually improving on logic while flat on market connection, and only this chart shows that.
- Module × topic mastery heatmap.
- Practice-frequency calendar.
- Difficulty distribution of attempted questions.

Charts must warn when a displayed date range spans multiple `prompt_version` values ([AI_SPEC §3.2](AI_SPEC.md#32-total-score)) — otherwise a rubric change looks like a change in ability.

## 1.7 Settings — `settings.py`

- **Profile:** display name, target roles, experience level.
- **LLM:** provider, API key entry (`type="password"`, session-only, never persisted — say so on screen), model override, "test key" button.
- Session token usage running total.
- **Data:** export everything as JSON; delete account and all data, with the community-question anonymization behavior stated *before* confirmation ([DATA_SPEC §11](DATA_SPEC.md#11-privacy--data-rights)).

## 1.8 Admin — `admin.py`

Rendered only when `profiles.is_admin` — **and enforced by RLS**. Hiding a page is not authorization; on a public app the page is reachable by URL.

Five tabs, spanning both banks:

| Tab | Contents |
|---|---|
| **Review queue** | Pending `review_requests`. Side-by-side: the submitted content and any existing near-duplicates. Approve (clones to verified, notifies) or reject (**reason required** — it is shown to the author). |
| **Reports** | Open `question_reports`, grouped by target, with reason and detail. Resolve · archive · promote. |
| **Bank management** | Full CRUD over both banks at every tier. Edit any field, including answer keys and `verification_level`. Delete archives; a separate double-confirmed **Purge** hard-deletes, for illegal content only. |
| **Bulk authoring** | Coverage scan → thin modules and topics → generate N drafts → accept/discard queue. Accepted drafts land at `community`/`published`, never verified ([CONTENT_SPEC §6.2](CONTENT_SPEC.md#62-bulk-authoring-admin)). |
| **Bank health** | Tier and verification-level counts, coverage gaps, low-quality content by net vote, dead source links, seed and export triggers. |

Three rules:

- **`verification_level` cannot be raised without a source supplied in the same action.** It is the only provenance signal left; letting an admin mark something `verified_interview` with one click and no URL is how the badge becomes meaningless.
- **Promotion goes through the stored procedure**, never three separate writes ([DATA_SPEC §8.3](DATA_SPEC.md#83-phase-2-repositories)).
- **Every destructive action names its blast radius before confirming** — how many notes, favorites, votes, and comments are attached.

---

# 2. Shared Components

| Component | Responsibility |
|---|---|
| `question_card.py` | Consistent question rendering everywhere, including the verification badge. One card, one look, every page. |
| `knowledge_card.py` | The same grammar for knowledge documents. |
| `verification_badge.py` | **The sole provenance signal in the product** ([D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance)). Never hand-rolled, never truncated, never hover-only. |
| `answer_key_view.py` | Renders and edits the five sections. Takes an explicit `allow_reveal` so hiding during interviews cannot be forgotten. |
| `comment_thread.py` | One-level replies, tombstone-aware, single query for a whole thread. |
| `vote_buttons.py` | ±1 with net score, both banks, optimistic update guarded against rerun double-fire. |
| `grounding_picker.py` | Knowledge selection with a live token-budget meter. |
| `confirm_dialog.py` | Irreversible actions. Always states what cannot be undone **before** the button, never after. |
| `score_radar.py` | Five-dimension Plotly radar; used on Dashboard, Review, Progress. |
| `rubric_breakdown.py` | Per-dimension score with anchor text and justification. |
| `filters.py` | The filter sidebar; emits a typed `QuestionFilters`, syncs to URL query params. |
| `api_key_gate.py` | Key prompt, validation, and the "no key set" banner. Single point of truth for key UX. |
| `empty_states.py` | Onboarding and zero-data states. Treated as a first-class component, not an afterthought. |

A UI pattern used twice becomes a component. The verification badge in particular must never be hand-rolled per page — inconsistent trust signaling is worse than none.

---

# 3. Streamlit Runtime Discipline

Streamlit re-executes the entire script on every interaction, in a single process shared by every concurrent user. These rules exist because violating them causes **duplicate paid API calls, cross-user data leaks, and OOM restarts** — not because they are tidy.

1. **No module-level mutable state.** A shared container means module globals are shared across *users*. Per-user state goes in `st.session_state` only.
2. **Typed session state.** All keys are declared in `app/state.py` with typed accessors. No string literals scattered across pages.
3. **Caching:**
   - `@st.cache_resource` — Supabase client, prompt loader. One per process.
   - `@st.cache_data(ttl=300, max_entries=64)` — question bank reads, knowledge documents. **Always bounded.** Caching a user-specific read requires `user_id` in the cache key.
   - **Never cache LLM calls or mutations.**
4. **Guard side effects.** Every write and every LLM call happens inside a `st.form` submit handler or a callback — never in the top-level script body. A rerun must never re-issue a paid API call.
5. **Idempotency keys.** Turn writes carry `(session_id, ordinal)` uniqueness so a double-submit cannot create a duplicate turn or a duplicate charge.
6. **Lazy imports** for heavy optional dependencies, to protect the ~30s cold start.
7. **`st.status` on every LLM call.** An unexplained 20-second freeze reads as a broken app; a labeled progress state reads as work being done.
8. **URL query params carry shareable view state** (filters, selected question, session id) so views survive reruns and can be linked.

---

# 4. Visual Conventions

- **Verification badge** is always visible on a question *and on a knowledge document*, color-coded by trust level, with a tooltip explaining what the level means. Since [D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance) removed the database constraint that used to guarantee verified content was sourced, this badge is the entire remaining trust mechanism — treat a missing badge as a data-integrity bug, not a cosmetic one.
- **Tier and verification are visually distinct.** They are different axes and users conflate them instantly if they share a shape or palette. Tier reads as a location ("Verified bank"); verification reads as an origin ("AI-generated").
- **Net vote score, never separate up and down counts.** Two adjacent numbers invite ratio-arithmetic and pile-ons; one signed number reads as a quality signal.
- **"Edited since voting"** appears on any community item modified after its first vote ([CONTENT_SPEC §2](CONTENT_SPEC.md#2-lifecycle)).
- **Scores** are always shown as five dimensions plus a total, never a bare number. A lone "72" is uninterpretable and invites the user to treat it as a grade rather than a diagnostic.
- **Anchors on demand:** hovering a dimension score shows the anchor text for that score, so the user learns the rubric by using it.
- **Plotly** for all charts, consistent color mapping per dimension across every page.
