# AI Specification

Provider abstraction, prompt architecture, the evaluation rubric, the interview state machine, and adaptive selection.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [DATA_SPEC.md](DATA_SPEC.md) · [DECISIONS.md](DECISIONS.md)

> Everything in this document lives in `core/engine/` and `core/llm/`, which **must not import `streamlit`**. If it decides a number, it has to be testable without a browser or a network.

---

# 1. LLM Abstraction

## 1.1 Provider protocol

```python
class LLMProvider(Protocol):
    name: str

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict,          # JSON Schema
        model: str,
        max_tokens: int = 2000,
        temperature: float = 0.2,
        timeout_s: float = 60.0,
    ) -> StructuredResult: ...

    def validate_key(self) -> KeyStatus: ...
```

`StructuredResult` carries `data: dict` (schema-validated), `model`, `input_tokens`, `output_tokens`, `latency_ms`, `raw`.

Implementations: `openai_provider.py`, `anthropic_provider.py`, `gemini_provider.py`. `registry.py` resolves provider by name and validates keys.

## 1.2 Requirements

| Rule | Detail |
|---|---|
| **Structured output always** | Never parse prose into scores. OpenAI → JSON Schema response format; Anthropic → tool-use with an input schema; Gemini → `responseSchema`. |
| **Validate anyway** | Schema-validate every response even when the provider claims conformance. One repair retry, then raise `LLMSchemaError`. |
| **Temperature policy** | Evaluator `0.0–0.2` (reproducibility is the whole point). Interviewer follow-ups `0.6–0.8`. Authoring `0.7`. |
| **Retry policy** | One retry on 429 / 5xx / timeout with exponential backoff and jitter. **Never retry a 401** — surface "your API key was rejected." |
| **Key handling** | Read from `st.session_state["llm_api_key"]`, passed as an argument. Never logged, stored, written to `raw_response`, or included in an error message. |
| **Default models** | Declared per provider in `core/config.py`, chosen for cost-efficiency, overridable per user in Settings. |

## 1.3 Cost transparency

The user pays ([D4](DECISIONS.md#d4--byo-llm-api-key-session-memory-only)), so every AI action displays estimated token usage on completion, and Settings shows a per-session running total. No cost data is persisted.

---

# 2. Prompt Architecture

## 2.1 Rules

1. Prompts live in `prompts/<name>.v<N>.md`. **No prompt text in Python source, ever.**
2. The filename version is the identity. A behavior-changing edit requires a **new file**, not an edit — old scores must remain interpretable ([D8](DECISIONS.md#d8--prompts-are-versioned-markdown-files)).
3. `core/prompts/loader.py` exposes `PromptSpec(name, version, template, sha256)` and caches by file.
4. Every persisted AI artifact stores `prompt_version` and `model`.
5. Templating is explicit `str.format`-style with a declared variable list; the loader validates that every declared variable was supplied and raises on an unsupplied one.

## 2.2 Prompt inventory

| File | Purpose | Output schema |
|---|---|---|
| `interviewer.v1.md` | Generate an adaptive follow-up from the transcript so far | `FollowUpSchema` |
| `evaluator.v1.md` | Score an answer on five anchored dimensions | `EvaluationSchema` |
| `coach.v1.md` | Post-session synthesis: patterns, priorities, drills | `CoachingSchema` |
| `question_author.v1.md` | Draft a new question with sourcing metadata | `QuestionDraftSchema` |
| `summarizer.v1.md` | Compress a long transcript for context reuse | `SummarySchema` |

## 2.3 Structure convention

Each file follows: `# Role` → `# Context` (templated) → `# Task` → `# Constraints` → `# Output`.

`evaluator.v1.md` additionally embeds the **full anchor table from §3.1 verbatim**. The anchors are the mechanism that makes scoring reproducible — a paraphrase of them is not the same prompt.

---

# 3. Evaluation Framework

## 3.1 The five dimensions and their anchors

Every answer is scored 0–4 on each dimension. These anchors are copied verbatim into `evaluator.v1.md`.

### Macro Framework — *did they structure the problem?*

| Score | Anchor |
|---|---|
| 0 | No structure. Assertions in arbitrary order. |
| 1 | Implicit structure only; the reader must reconstruct it. |
| 2 | States a framework but doesn't apply it consistently. |
| 3 | Clear framework, applied consistently, appropriate to the question. |
| 4 | Clear framework plus an explicit statement of what would falsify it or where it breaks down. |

### Economic Logic — *are the mechanisms correct?*

| Score | Anchor |
|---|---|
| 0 | Materially wrong causality, or an inverted relationship. |
| 1 | Directionally right; mechanism unstated or muddled. |
| 2 | Correct mechanism, missing key transmission steps. |
| 3 | Correct and complete chain of transmission. |
| 4 | Correct chain plus second-order effects, lags, or offsetting channels. |

### Evidence — *are the right indicators invoked?*

| Score | Anchor |
|---|---|
| 0 | No data or indicators referenced. |
| 1 | Vague references ("the data suggests"). |
| 2 | Names relevant indicators without interpreting them. |
| 3 | Names the right indicators and interprets levels and trends correctly. |
| 4 | Right indicators, correct interpretation, and states what data would change the view. |

### Market Connection — *can they get from economics to price?*

| Score | Anchor |
|---|---|
| 0 | No market implication drawn. |
| 1 | Asserts a market view with no link to the preceding analysis. |
| 2 | Links to one asset class only. |
| 3 | Coherent cross-asset implication (rates, FX, credit, equities as relevant). |
| 4 | Cross-asset implication plus positioning or valuation context, or an explicit risk-reward. |

### Communication — *is it concise and structured?*

| Score | Anchor |
|---|---|
| 0 | Rambling; no discernible conclusion. |
| 1 | Conclusion buried at the end. |
| 2 | Reasonable structure, notably verbose or repetitive. |
| 3 | Answer-first, tight, well-sequenced. |
| 4 | Answer-first, tight, and calibrated in its confidence language. |

## 3.2 Total score

```python
BASE_WEIGHTS = {
    "framework":     0.25,
    "logic":         0.25,
    "evidence":      0.15,
    "market":        0.20,
    "communication": 0.15,
}

# Policy institutions reward evidence over tradeable expression.
MODE_WEIGHTS = {
    "hedge_fund":   BASE_WEIGHTS,
    "sell_side":    BASE_WEIGHTS,
    "central_bank": {**BASE_WEIGHTS, "market": 0.15, "evidence": 0.20},
    "ifi":          {**BASE_WEIGHTS, "market": 0.15, "evidence": 0.20},
}

def total_score(scores: dict[str, int], mode: str) -> int:
    w = MODE_WEIGHTS[mode]
    weighted = sum(w[k] * scores[k] for k in w)   # 0.0 – 4.0
    return round(weighted / 4 * 100)              # 0 – 100
```

Two rules that matter:

1. **The total is computed in Python from the LLM's dimension scores.** The model is never asked to produce the total — that would reintroduce exactly the determinism leak the anchors exist to close.
2. **Weights are versioned with the evaluator prompt.** Changing a weight requires a new `prompt_version`, and trend charts must warn when a displayed range spans versions.

## 3.3 What the evaluator must and must not return

**Must return:** dimension scores each with a one-sentence justification, concrete strengths, concrete gaps, an **outline** of a stronger answer, and knowledge-base slugs to read.

**Must not return:** a polished model answer the candidate could memorize.

> This is the single most important guardrail in the product. An interview trainer that hands out scripts trains the wrong skill — it produces candidates who sound rehearsed and collapse on the first follow-up. It is stated as a constraint in the prompt **and** asserted as a property in the golden test suite ([IMPLEMENTATION_GUIDE §5.4](IMPLEMENTATION_GUIDE.md#54-golden-evaluation-set-testsgolden)).

---

# 4. Interview Engine

## 4.1 Interviewer modes

Mode changes the persona, the follow-up style, and the scoring weights (§3.2).

| Mode | Pushes on | Signature follow-up |
|---|---|---|
| `hedge_fund` | Market implication, trade expression, cross-asset impact, risk/reward, what's already priced | "Fine — what's the trade, what's your risk, and what does the market already believe?" |
| `central_bank` | Data interpretation, policy trade-offs, communication, mandate constraints | "How would you present this to a policy committee that disagrees?" |
| `ifi` | Policy diagnosis, structural country analysis, program design, recommendations | "What's the binding constraint, and what would you actually recommend?" |
| `sell_side` | Forecast defensibility, client framing, differentiation from consensus | "Consensus says otherwise. Why are they wrong?" |

## 4.2 Session state machine

Pure, in `core/engine/session.py`.

```
CONFIGURING
    │  user picks mode, institution, length, modules, adaptive on/off
    ↓
SELECTING ───────────────────────────────────┐
    │  selector picks the next seed question  │
    ↓                                         │
ASKING                                        │
    │  turn persisted (question_text) BEFORE display
    ↓                                         │
AWAITING_ANSWER                               │
    │  answer + elapsed persisted BEFORE any LLM call
    ↓                                         │
EVALUATING                                    │
    │  evaluator → Evaluation persisted       │
    ↓                                         │
DECIDING ─────────────────────────────────────┘
    │  follow-up warranted?  ─yes→ ASKING (is_followup=true)
    │  turns remaining?      ─yes→ SELECTING
    ↓ no
SUMMARIZING
    │  coach.v1 → session summary; overall_score written
    ↓
COMPLETE
```

> **Invariant:** the user's typed answer is written to `interview_turns` **before** any LLM call is made. An API failure must never cost someone a five-minute answer. Non-negotiable, and covered by an integration test.

Every state also has an error edge back to a recoverable state — `EVALUATING` on failure returns to `DECIDING` with the turn stored unevaluated and a manual re-evaluate action offered.

## 4.3 Follow-up policy

A follow-up is generated when **any** of these hold, capped at **2 per seed question**:

- Any dimension scored ≤ 2 → probe that specific weakness.
- `market` ≤ 2 in `hedge_fund` mode → always probe market implication.
- The evaluator flagged an asserted claim as unsupported.

Follow-ups are generated by `interviewer.v1.md` with the transcript so far as context, and are scored by the same rubric. Beyond ~6 turns, earlier turns are passed as a `summarizer.v1` compression rather than in full, to cap token growth.

## 4.4 Session composition

`config.planned_turns` defaults to 5 seed questions. Target mix once history exists:

- **60%** from the user's weakest topics (adaptive, §5)
- **25%** matching the target institution's focus areas
- **15%** exploration — topics with no history at all

Adaptive mode activates once `attempts >= 5` exists in at least 3 topics. Before that, selection is: institution match → difficulty matched to `experience_level` → random within the eligible pool, seeded by `config.seed` for reproducibility.

---

# 5. Adaptive Question Selection

`core/engine/selector.py`. A **pure function** of `(mastery_rows, candidate_questions, filters, exclude_ids, config, rng)` → ordered list. No I/O, fully unit-tested, deterministic under a fixed seed.

## 5.1 Weakness score

For each `(module, topic)` with history:

```python
def weakness(row: MasteryRow, now: datetime) -> float:
    deficit    = (100.0 - row.ewma_total) / 100.0     # 0..1, higher = weaker
    days       = (now - row.last_practiced_at).days
    staleness  = min(days / 30.0, 1.0)                # 0..1
    confidence = min(row.attempts / 5.0, 1.0)         # damp low-n noise
    return confidence * (0.75 * deficit + 0.25 * staleness)
```

Topics with no history receive a fixed exploration score of `0.45` — high enough to surface, not high enough to dominate.

The `confidence` factor exists because a single bad answer in a topic should not convince the system you're weak there. It ramps in over five attempts.

## 5.2 Mastery update (EWMA)

On every `evaluations` insert, for that turn's `(module, topic)`:

```python
ALPHA = 0.3   # recent answers weigh more; roughly the last 6 attempts dominate

new_ewma = ALPHA * observed + (1 - ALPHA) * old_ewma   # first observation: new = observed
```

Applied per dimension and to the total. Implemented as a Postgres trigger function so no write path can skip it, with script support for full recomputation from `evaluations` — [`topic_mastery` is a cache, not a source of truth](DATA_SPEC.md#51-topic_mastery).

## 5.3 Selection algorithm

1. Fetch eligible questions via `list_for_selection`, respecting tier filters and excluding this session's questions plus anything attempted in the last 30 days.
2. Score each: `0.60 * weakness(module, topic) + 0.25 * difficulty_fit + 0.15 * institution_match`.
3. `difficulty_fit` maps `experience_level` and `ewma_total` to a target difficulty — exact match `1.0`, one step away `0.5`, two steps `0.0`.
4. **Sample without replacement using softmax over scores** (temperature `0.5`) rather than taking the top-k. Pure top-k makes every session identical, which defeats the purpose of a training tool.
5. Enforce the composition quotas from §4.4.

## 5.4 Testable properties

The unit suite asserts: determinism under a fixed seed; quota compliance; that no excluded question is ever returned; that a user with one very weak topic sees it over-represented but not exclusively; and that an empty mastery table degrades gracefully to the non-adaptive path.
