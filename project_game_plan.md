# Project Game Plan: Data-Center Demand Growth & Generation-Interconnection Queue Congestion

*Summer 2026 independent research project — Luke W. Jones*

---

## 1. The Research Question

**Do U.S. regions absorbing the fastest data-center-driven electricity demand growth also show slower-clearing, more congested interconnection queues for new generation — meaning the approval pipeline itself, not physical construction, is becoming the binding constraint on new supply?**

**Why this question:** the "AI is straining the grid" narrative is everywhere, but it rests on two separate, well-documented facts (data centers are driving a demand surge; interconnection queues are congested and slow) that nobody has actually tested *against each other* at the regional level. The literature review confirmed this directly: no published study cross-references regional demand growth with regional queue-completion outcomes. That gap is the project.

**The motivating context:** under FERC's post-2023 rules, U.S. transmission interconnection is sorted by commercial readiness, not strategic importance — there's no mechanism for treating a data center's request differently from anyone else's. The UK, facing the same congestion, chose the opposite path in 2025: an explicit fast lane for data centers and other "strategically important" projects. The U.S. has no equivalent, and the most direct workaround — co-locating a data center at an existing power plant to bypass the shared grid — is itself legally unsettled, as FERC's 2024 rejection of the Talen-Amazon Susquehanna expansion showed. That's part of why financing entirely new, purpose-built local generation (e.g., enhanced geothermal built specifically to serve a data center) has become an attractive alternative — it sidesteps both the queue and the co-location fight at once.

**Why three possible outcomes, not one expected answer:**
- **Positive** (faster demand growth ↔ worse queue performance) → supports the "shared, competed-for grid resources" mechanism; strengthens the case for local/alternative generation as a genuine release valve.
- **Null** (no relationship) → suggests queue dysfunction is a *national*, structural problem independent of where demand concentrates — an argument for broad reform (like Order 2023) over region-specific fixes (like the UK's approach).
- **Negative** (faster demand growth ↔ *better* queue performance) → the most surprising finding; would suggest visible pressure induces adaptive institutional response, shifting the interesting question to "what are those regions doing differently."

All three are real, reportable findings. The project is not built to find a specific answer — it's built so that whichever answer comes out is credible and interpretable.

---

## 2. Deliverable Format

**A 2–3 page memo, bottom-line-up-front, backed by a full technical appendix.**

Why: an academic-paper structure (abstract → literature → methodology → results) is fully auditable but buries the finding and doesn't demonstrate client-facing communication — the thing you've identified as your actual differentiator. A pure memo with no appendix risks looking like it's hiding thin work. Doing both — memo primary, rigorous appendix behind it — is also literally how E3, Brattle, and Analysis Group structure real client deliverables, so producing it this way is itself a small demonstration that you understand the audience.

---

## 3. Workflow by Phase

### Phase 0 — Literature & Precedent Review — ✅ Complete

**What we did:** ran the Research feature against four questions — (1) has this cross-reference been done before, (2) current status of FERC's co-located-load rulemaking, (3) how Ireland/Singapore/UK handle this differently, (4) evidence on whether Order 2023 reforms are working.

**Key takeaways carried forward:**
- The gap is confirmed real — this is genuinely novel.
- FERC regulatory timeline: Nov 2024 Susquehanna rejection → Feb 2025 PJM show-cause (EL25-49) → Oct 2025 DOE-directed large-load ANOPR (RM26-4) → Dec 2025 PJM co-location order → **June 18, 2026: six region-specific show-cause orders** (PJM, SPP, NYISO, MISO, CAISO, ISO-NE), each with its own 60-day clock. This is a live, moving regulatory picture — cite it as of writing, don't assume it's settled.
- Johnston, Liu & Yang's NBER working paper is the closest methodological template on the queue side (hand-collected PJM data, congestion-externality framing, dynamic model of withdrawal behavior) — worth reading closely before finalizing the regression spec.
- ERCOT needs separate treatment: it's not FERC-jurisdictional and runs its own large-load process, so it can't be pooled naively with FERC-jurisdictional RTOs.
- International cases (Ireland, Singapore, UK) are **discussion material, not data** — they illustrate alternative administrative regimes, but none of them gives you a demand-vs-generation-queue dataset the way the U.S. combination of EIA-930 + LBNL Queued Up does.

### Phase 1 — Data Acquisition

| Data | What it gives us | Source |
|---|---|---|
| **EIA-930** (Hourly Electric Grid Monitor) | Hourly demand by balancing authority since 2015 — the basis for measuring *regional* demand growth | Public API / bulk CSV, eia.gov |
| **LBNL "Queued Up"** (latest edition) | Project-level generation/storage interconnection records: request date, in-service date, status, region, technology — the basis for completion rate and wait-time-by-cohort | Excel workbook, emp.lbl.gov/queues |

**Tool:** Claude Code, two parallel sessions (Open in New Tab, or worktrees if you want stricter isolation) — one pulling EIA-930, one parsing the LBNL workbook. **Why:** these are genuinely independent tasks that never touch the same files, which is exactly the case for parallelizing rather than doing them one after another.

A good subagent moment here: have a subagent read through LBNL's full data dictionary/codebook (it's long) and report back just the columns needed for the panel — keeps that dump out of your main working context.

**Model:** mostly Sonnet 5 — this is well-specified execution (write the API pull, parse the known file format) once you know what you're pulling.

**Known wrinkle to plan around:** some sub-balancing-authorities (e.g., Duke Energy Progress, PacifiCorp West) don't publish standalone EIA-930 demand and need to be mapped to a parent BA. Document this mapping explicitly rather than silently dropping or merging regions.

### Phase 2 — Panel Construction

**What:** build the actual analysis dataset — regional demand-growth rates joined to regional completion-rate and wait-time metrics, by vintage cohort year.

**Tool:** one continuous Claude Code session, not parallelized. **Why:** the judgment calls here (how to define "region" consistently across two differently-structured datasets, how to handle projects that changed status between editions) need to stay coherent — this is exactly the kind of task that gets worse, not better, if split across workers.

**Model:** Opus 5 for the actual matching-logic decisions (these are genuine judgment calls with more than one defensible answer); Sonnet 5 once the logic is decided and it's just execution.

**The methodological wrinkle from Phase 0, restated here because this is where it bites:** queue dynamics shifted materially in 2023–2025 partly *because of* FERC's Order 2023 reform (forced resubmissions, purged speculative projects), not purely from demand pressure. Build a way to distinguish "reform effect" from "demand effect" in the same window — e.g., a period indicator, or treating pre-/post-2023 cohorts separately — before you interpret any correlation as demand-driven.

### Phase 3 — Analysis

**Method:** regression (or cohort-survival / time-to-completion specification) with completion rate and median wait time as outcomes; regional demand-growth rate as the key explanatory variable.

**Controls to include, and why each matters:**
- **ISO/RTO vs. non-ISO structure** — Order 2023's impact differs sharply by market type; without this control you'd conflate "demand growth" with "which regulatory regime a region happens to have."
- **Baseline pre-surge backlog** — a region that was already congested before data centers arrived will look "worse" regardless of the demand-growth story.
- **Technology mix** — gas clears the queue faster than renewables/storage; a region's queue composition alone can drive completion rates.
- **FERC jurisdiction** (ERCOT flagged separately) — different rules entirely, shouldn't be pooled without a control or separate treatment.

**Tool:** Claude Code. **Model:** Opus 5 for specifying the regression (what functional form, what to control for, how to handle the 2023 regime shift), Sonnet 5 for running diagnostics and iterating once the spec is locked.

### Phase 4 — Writing

**Deliverable:** the memo (bottom-line-up-front: the question, the answer, why it matters) and the technical appendix (full data/methodology/robustness detail an interviewer could grill you on).

**Tool:** either stays in Claude Code if drafting in Markdown (clean conversion to PDF later), or a regular chat session using the docx skill if you want a properly formatted Word file.

**Model:** Opus 5 — the actual argument has to be airtight, and this is exactly the kind of judgment-heavy writing where the better model earns its cost.

### Phase 5 — Polish

- Technical appendix figures: matplotlib, inside the same Claude Code session.
- Optional portfolio version: a clean one-pager built in Claude Design — worth doing once the analysis is locked, since this is specifically the kind of polished visual summary that travels well in a recruiting conversation.

---

## 4. Quick Reference

| Phase | Claude Surface | Model | Parallel? |
|---|---|---|---|
| 0. Literature review | Research feature (this chat) | — | — |
| 1. Data acquisition | Claude Code, 2 tabs | Sonnet 5 | Yes |
| 2. Panel construction | Claude Code, 1 session | Opus 5 → Sonnet 5 | No |
| 3. Analysis | Claude Code, 1 session | Opus 5 → Sonnet 5 | No |
| 4. Writing | Claude Code or chat + docx skill | Opus 5 | No |
| 5. Polish | Claude Code (charts) / Claude Design (one-pager) | Sonnet 5 | — |

---

## 5. Risks to Watch

- **The 2023 regime change confound** — the single biggest threat to a clean result. Design for it from the start, don't discover it after running the regression.
- **ERCOT** — non-FERC-jurisdictional, separate large-load process. Treat as its own case, not pooled data.
- **Data coverage gaps** — in-service dates have been incomplete in past LBNL editions (available for as little as ~61% of operational projects in some editions); EIA-930 sub-BA mapping needs explicit, documented handling. Both will affect wait-time estimates if not addressed head-on.
- **Secondary-source queue figures** (e.g., some aggregator numbers for ERCOT's large-load queue) don't always match primary LBNL/ERCOT filings — verify against the primary source before citing anything specific in the final memo.

---

## 6. Looking Ahead

This project is also the "diagnosis" half of a two-part portfolio: the winter-break project (Pyomo-based battery dispatch optimization for data-center load firming, likely extended into a stochastic program once ORF 309 is done) is the "response" half — literally the decision layer on top of what this project establishes about where and how grid constraints bind. Worth revisiting Ko/Modo Energy at that point, once real price-spread and storage-revenue assumptions are actually needed.
