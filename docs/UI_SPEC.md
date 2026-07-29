# UI Specification

Page-by-page behavior, shared components, and Streamlit runtime discipline.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [AI_SPEC.md](AI_SPEC.md)

> **Pages are UI only.** No SQL, no prompt text, no scoring arithmetic. Every bullet below maps to an engine or repository call ([ARCHITECTURE §2](ARCHITECTURE.md#2-layer-rules)).

---

# 1. Pages

## 1.1 Dashboard — `1_Dashboard.py`

- Questions attempted, sessions completed, rolling 30-day average total score.
- Five-dimension radar of current mastery (`score_radar`).
- **Three weakest topics**, each with a one-click "drill this" that opens a focused session.
- Recent sessions with scores; resume any session still `active`.
- Practice-frequency sparkline.

**Empty state matters more than the populated state here.** A brand-new user must see an onboarding card — set target roles → add an API key → start your first interview — not four zeroed charts. Zeroed charts read as a broken app.

## 1.2 Question Bank — `2_Question_Bank.py`

- Search box ([CONTENT_SPEC §5.1](CONTENT_SPEC.md#51-level-1--full-text-v1)) plus filter sidebar, with tier and verification-level filters prominent.
- Paginated question cards: text, module/topic, difficulty, institutions, **verification badge**, source link, upvote, favorite, report.
- Expand for notes (autosaved), seed follow-up questions, and your attempt history on that question.
- "Practice this" (single question + evaluation) and "Add to session."
- "Create question" → AI-assisted authoring ([CONTENT_SPEC §6](CONTENT_SPEC.md#6-ai-assisted-authoring)) or manual entry.

## 1.3 Interview — `3_Interview.py`

- **Config step:** mode, institution, length, modules, adaptive toggle.
- **Turn view:** one question, answer textarea, elapsed timer, submit.
- **After submit:** rubric breakdown, strengths and gaps, then either a follow-up or the next question.
- "End early" marks the session `completed` with the turns scored so far — never `abandoned` silently.
- If no API key is set, warn clearly up front with a link to Settings rather than failing at submit time after the user has typed five paragraphs.

State machine: [AI_SPEC §4.2](AI_SPEC.md#42-session-state-machine). The page renders states; it does not implement transitions.

## 1.4 Review — `4_Review.py`

- Session list → turn-by-turn drill-down.
- Per turn: the question as asked, your answer, five dimension scores with justifications, gaps, improved outline, suggested readings (linked into the Knowledge page).
- Session-level coaching synthesis (`coach.v1`).
- **"Retry this question"** starts a fresh single-question attempt and shows the delta against your prior score — the most directly motivating interaction in the product.

## 1.5 Knowledge — `5_Knowledge.py`

- Browse by module, search by title and topic, render Markdown.
- "Related questions" panel filtered by the document's `modules` and `topics`.
- Related-concept links from the document's `related` frontmatter.

## 1.6 Progress — `6_Progress.py`

- Total score trend over time.
- **Per-dimension trends** — the most actionable view in the app. Someone plateauing overall is usually improving on logic while flat on market connection, and only this chart shows that.
- Module × topic mastery heatmap.
- Practice-frequency calendar.
- Difficulty distribution of attempted questions.

Charts must warn when a displayed date range spans multiple `prompt_version` values ([AI_SPEC §3.2](AI_SPEC.md#32-total-score)) — otherwise a rubric change looks like a change in ability.

## 1.7 Settings — `7_Settings.py`

- **Profile:** display name, target roles, experience level.
- **LLM:** provider, API key entry (`type="password"`, session-only, never persisted — say so on screen), model override, "test key" button.
- Session token usage running total.
- **Data:** export everything as JSON; delete account and all data, with the community-question anonymization behavior stated *before* confirmation ([DATA_SPEC §11](DATA_SPEC.md#11-privacy--data-rights)).

## 1.8 Admin — `9_Admin.py`

- Rendered only when `profiles.is_admin` — **and enforced by RLS**. Hiding a page is not authorization; the page is reachable by URL on a public app.
- Report queue, tier promotion, question editor, bulk AI authoring queue, bank-health stats (dead source links, tier counts, coverage gaps by module), seed and export triggers.

---

# 2. Shared Components

| Component | Responsibility |
|---|---|
| `question_card.py` | Consistent question rendering everywhere, including the verification badge. One card, one look, every page. |
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

- **Verification badge** is always visible on a question, color-coded by trust tier, with a tooltip explaining what the level means.
- **Scores** are always shown as five dimensions plus a total, never a bare number. A lone "72" is uninterpretable and invites the user to treat it as a grade rather than a diagnostic.
- **Anchors on demand:** hovering a dimension score shows the anchor text for that score, so the user learns the rubric by using it.
- **Plotly** for all charts, consistent color mapping per dimension across every page.
