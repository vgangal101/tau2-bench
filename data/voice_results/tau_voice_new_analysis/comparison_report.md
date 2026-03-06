# τ-voice Results Comparison Report

Comparison of old results (`papers/tau-voice/results/`) vs new results (`data/exp/tau_voice_new_analysis/paper/`).

Both datasets cover 278 tasks across 3 domains (retail=114, airline=50, telecom=114) and 3 providers (Google, OpenAI, xAI).

## What changed

- **Two OpenAI models**: The old paper had a single OpenAI model (`gpt-4o-realtime-preview`, now called `gpt-realtime-2025-08-28` — same model, renamed). The new results add a second, newer model: `gpt-realtime-1.5`. The gpt-2025-08-28 comparison is therefore a **same-model** comparison; performance differences come from updated tasks and re-runs, not model changes.
- **Updated airline tasks**: Same 50-task count but the task set has been revised. This also changes the text baselines for airline and therefore the "All" domain averages.
- **Updated retail tasks**: Same 114-task count but the task set has been revised (smaller change than airline). All providers were re-run. Retail text baselines shifted slightly (text\_sota: 81.6% → 81.0%, text\_nonthinking: 74.0% → 76.0%).
- **Telecom unchanged**: Telecom tasks and data for Google, xAI, and OpenAI `gpt-2025-08-28` are the same as the old paper. Only the new `gpt-realtime-1.5` model adds new telecom data.
- **Full single-factor ablations available**: control, control\_audio, control\_accents, control\_behavior, and regular — for all 4 models (Google, both OpenAI, xAI).
- **Text baselines changed** due to updated airline and retail tasks:
  - text\_sota (GPT-5): All 80.0% → 84.7%, airline 62.5% → 83.0%, retail 81.6% → 81.0%, telecom 95.8% → 90.0%
  - text\_nonthinking (GPT-4.1): All 54.7% → 54.3%, airline 56.0% → 53.0%, retail 74.0% → 76.0%, telecom 34.0% → 34.0%

---

## 1. Main Results (Pass@1)

### Overall (All domains)

| Provider | Model | Old Clean | New Clean | Δ | Old Realistic | New Realistic | Δ | Old Gap | New Gap | Δ |
|----------|-------|-----------|----------|---|---------------|--------------|---|---------|--------|---|
| Google | gemini-live-2.5-flash | 29.2% | 28.9% | -0.3pp | 24.5% | 24.6% | +0.2pp | -4.8pp | -4.3pp | +0.5pp |
| OpenAI | gpt-realtime-1.5 | 33.1% | **48.5%** | **+15.4pp** | 19.3% | **35.0%** | **+15.7pp** | -13.8pp | -13.5pp | +0.3pp |
| OpenAI | gpt-realtime-2025-08 | 33.1% | **40.7%** | **+7.6pp** | 19.3% | **34.3%** | **+15.0pp** | -13.8pp | -6.4pp | **+7.3pp** |
| xAI | xai-realtime | 42.3% | **50.7%** | **+8.4pp** | 30.3% | **37.7%** | **+7.5pp** | -12.0pp | -13.0pp | -1.0pp |

### Rankings

**Clean (control):**
1. xAI: 50.7% (was 42.3%, still #1)
2. OpenAI gpt-1.5: 48.5% (new)
3. OpenAI gpt-2025-08: 40.7% (was 33.1%)
4. Google: 28.9% (was 29.2%)

**Realistic (regular):**
1. xAI: 37.7% (was 30.3%, still #1)
2. OpenAI gpt-1.5: 35.0% (new model)
3. OpenAI gpt-2025-08: 34.3% (was 19.3% — same model, +15pp from updated tasks)
4. Google: 24.6% (was 24.5%)

### Per-domain breakdown

| Domain | Provider | Model | Old Clean | New Clean | Δ | Old Realistic | New Realistic | Δ |
|--------|----------|-------|-----------|----------|---|---------------|--------------|---|
| Retail | Google | gemini | 39.5% | 38.6% | -0.9 | 28.1% | 28.1% | = |
| Retail | OpenAI | gpt-1.5 | 39.5% | **69.3%** | **+29.8** | 15.8% | **43.9%** | **+28.1** |
| Retail | OpenAI | gpt-2025-08 | 39.5% | **53.5%** | **+14.0** | 15.8% | **33.3%** | **+17.5** |
| Retail | xAI | xai-realtime | 42.1% | 48.2% | +6.1 | 20.2% | **36.8%** | **+16.7** |
| Airline | Google | gemini | 28.0% | 28.0% | = | 26.0% | 30.0% | +4.0 |
| Airline | OpenAI | gpt-1.5 | 36.0% | **48.0%** | **+12.0** | 28.0% | **40.0%** | **+12.0** |
| Airline | OpenAI | gpt-2025-08 | 36.0% | 44.0% | +8.0 | 28.0% | **44.0%** | **+16.0** |
| Airline | xAI | xai-realtime | 26.0% | **46.0%** | **+20.0** | 34.0% | 36.0% | +2.0 |
| Telecom | Google | gemini | 20.2% | 20.2% | = | 19.3% | 15.8% | -3.5 |
| Telecom | OpenAI | gpt-1.5 | 23.7% | 28.1% | +4.4 | 14.0% | **21.1%** | **+7.0** |
| Telecom | OpenAI | gpt-2025-08 | 23.7% | 24.6% | +0.9 | 14.0% | **25.4%** | **+11.4** |
| Telecom | xAI | xai-realtime | 58.8% | 57.9% | -0.9 | 36.6% | 40.4% | +3.7 |

**Clean > Realistic pattern by domain:**

The aggregate result (Clean > Realistic for all providers) masks important per-domain exceptions:

| Domain | Pattern | Details |
|--------|---------|---------|
| **Retail** | **Holds for all models** | Largest degradations in the benchmark. Deltas range from -10.5pp (Google) to -25.4pp (gpt-1.5). Retail is the domain where speech complexity most reliably hurts performance. |
| **Airline** | **Breaks for 2 of 4 models** | Google: Realistic *exceeds* Clean by +2.0pp. gpt-2025-08: Realistic = Clean (44.0%/44.0%, delta=0). Only gpt-1.5 (-8.0pp) and xAI (-10.0pp) show the expected pattern. The small task count (n=50) means these reversals could be noise, but gpt-2025-08's exact zero delta is striking. |
| **Telecom** | **Holds for 3 of 4 models** | gpt-2025-08 shows a small reversal: Realistic slightly exceeds Clean (+0.9pp). All others follow the expected pattern, with xAI showing the largest drop (-17.5pp). |

In the old paper, airline/xAI was also an exception (Realistic exceeded Clean by +8.0pp), but with the updated tasks this has flipped to -10.0pp. The exceptions are concentrated in **gpt-2025-08** (zero or positive delta in both airline and telecom) and **Google on airline** (+2.0pp). For gpt-2025-08, this suggests the model is unusually robust to speech complexity on non-retail tasks — or that its baseline Clean performance on those tasks is lower than expected.

**Key findings:**
- **All providers show higher scores**, driven by updated retail and airline tasks. Since gpt-2025-08-28 is the same model as the old paper's `gpt-4o-realtime-preview`, its gains (+7.6pp Clean, +15.0pp Realistic overall) reflect task changes and re-runs, not model improvements.
- **OpenAI gpt-realtime-1.5 is the standout new model**: 69.3% retail Clean is the single best per-domain score, and 48.5% aggregate Clean is close to xAI's 50.7%.
- **xAI leads in Realistic** at 37.7%, followed closely by both OpenAI models (~35%). xAI also saw massive gains on airline Clean (+20pp) with the updated tasks.
- **Google is stable**: essentially flat at the aggregate level. Retail control slightly down (-0.9pp) but airline Realistic improved (+4pp with new tasks).
- **gpt-2025-08 airline anomaly**: the only configuration where Realistic equals Clean (44.0%/44.0%, delta=0). Speech complexity has zero impact on this model for the new airline tasks.

---

## 2. Core Voice Metrics

| Provider | Model | Metric | Old Clean | New Clean | Δ | Old Realistic | New Realistic | Δ |
|----------|-------|--------|-----------|----------|---|---------------|--------------|---|
| Google | gemini | Resp. Latency | 1.36s | 1.37s | +0.01 | 1.44s | 1.42s | -0.02 |
| Google | gemini | Resp. Rate | 0.984 | 0.960 | -0.02 | 0.866 | 0.788 | -0.08 |
| Google | gemini | Interrupt Rate | 0.095 | 0.080 | -0.02 | 0.244 | 0.220 | -0.02 |
| **OpenAI** | **gpt-1.5** | **Resp. Latency** | **3.65s** | **1.69s** | **-1.96** | **3.24s** | **1.39s** | **-1.85** |
| **OpenAI** | **gpt-1.5** | **Resp. Rate** | **0.892** | **0.993** | **+0.10** | **0.779** | **0.999** | **+0.22** |
| **OpenAI** | **gpt-1.5** | **Interrupt Rate** | **0.407** | **0.010** | **-0.40** | **0.340** | **0.135** | **-0.21** |
| **OpenAI** | **gpt-2025-08** | **Resp. Latency** | **3.65s** | **1.69s** | **-1.96** | **3.24s** | **1.47s** | **-1.77** |
| **OpenAI** | **gpt-2025-08** | **Resp. Rate** | **0.892** | **0.959** | **+0.07** | **0.779** | **0.984** | **+0.21** |
| **OpenAI** | **gpt-2025-08** | **Interrupt Rate** | **0.407** | **0.021** | **-0.39** | **0.340** | **0.134** | **-0.21** |
| xAI | xai-realtime | Resp. Latency | 0.90s | 1.05s | +0.15 | 0.99s | 1.15s | +0.16 |
| xAI | xai-realtime | Resp. Rate | 0.952 | 0.921 | -0.03 | 0.907 | 0.913 | +0.01 |
| xAI | xai-realtime | Interrupt Rate | 0.490 | 0.435 | -0.06 | 1.046 | 0.843 | **-0.20** |

**Key findings:**
- **Both OpenAI models show dramatically improved conversational dynamics** vs the old paper: latency roughly halved (3.65s → ~1.69s Clean), response rate near-perfect (99%), and Clean interrupt rate dropped from 41% to 1–2%. Since gpt-2025-08 is the same model as the old paper, these voice metric changes reflect re-runs on updated tasks (retail, airline) plus telecom being unchanged — suggesting the old numbers were influenced by the previous task set.
- **gpt-1.5 is slightly better than gpt-2025-08** in response rate (99.3% vs 95.9% Clean) and interrupt rate (1.0% vs 2.1% Clean).
- **xAI interruption rate improved** substantially (1.05 → 0.84 Realistic, -0.20 from old paper). Still the highest of all providers.
- **Google is stable** with minor shifts. Response rate in Realistic dropped slightly (0.87 → 0.79).

---

## 3. Voice Quality (Realistic condition)

### Aggregated metrics

| Metric | Google (old→new) | OpenAI gpt-1.5 (old→new) | OpenAI gpt-2025-08 (old→new) | xAI (old→new) |
|--------|-----------------|--------------------------|------------------------------|--------------|
| Latency | 1.13 → 1.09 | **2.22 → 0.90** | **2.22 → 0.94** | 0.99 → 1.15 |
| Responsiveness | 72% → 66% | **69% → 100%** | **69% → 99%** | 85% → 83% |
| Interrupt Rate | 24% → 22% | **34% → 14%** | **34% → 13%** | 105% → **84%** |
| Selectivity | 52% → 58% | **75% → 6%** | **75% → 7%** | 52% → 57% |

### Detailed voice quality (Realistic, All domains)

| Metric | Google (old→new) | OpenAI gpt-1.5 (old→new) | OpenAI gpt-2025-08 (old→new) | xAI (old→new) |
|--------|-----------------|--------------------------|------------------------------|--------------|
| Response Rate | 0.87 → 0.79 | **0.78 → 1.00** | **0.78 → 0.98** | 0.91 → 0.91 |
| Response Latency | 1.44s → 1.42s | **3.24s → 1.39s** | **3.24s → 1.47s** | 0.99s → 1.15s |
| Yield Rate | 0.57 → 0.53 | **0.60 → 1.00** | **0.60 → 1.00** | 0.80 → 0.75 |
| Yield Latency | 0.82s → 0.76s | **1.20s → 0.42s** | **1.20s → 0.41s** | 1.00s → 1.15s |
| Backchannel Err | 0.10 → 0.12 | **0.04 → 0.98** | **0.04 → 0.98** | 0.19 → 0.07 |
| Vocal Tic Err | 0.66 → 0.66 | **0.28 → 0.95** | **0.28 → 0.96** | 0.47 → 0.42 |
| Non-Directed Err | 0.70 → 0.50 | **0.42 → 0.90** | **0.42 → 0.86** | 0.79 → 0.79 |

**Key findings:**
- **Both OpenAI models share the same behavioral profile shift**: near-perfect responsiveness (99–100%) but near-zero selectivity (6–7%). They respond to almost everything — backchannels, vocal tics, non-directed speech.
- **The two OpenAI models are nearly identical in voice quality**. The performance gap is entirely in task completion (Pass@1), not conversational dynamics.
- **xAI selectivity improved**: backchannel error rate dropped from 0.19 to 0.07, and overall interrupt rate dropped from 1.05 to 0.84.
- **Google non-directed speech handling improved**: error rate dropped from 0.70 to 0.50.

---

## 4. Voice vs Text Gap

The voice\_vs\_text table now compares against `text_sota` (GPT-5 reasoning), which changed for airline (62.5% → 83.0%) and slightly for retail (81.6% → 81.0%) and telecom (95.8% → 90.0%).

### Against text\_nonthinking (GPT-4.1) — comparable to old paper

| Provider | Model | Text (old→new) | New Realistic | Gap (old→new) |
|----------|-------|---------------|--------------|--------------|
| Google | gemini | 54.7% → 54.3% | 24.6% | -30.2pp → -29.7pp |
| OpenAI | gpt-1.5 | 54.7% → 54.3% | 35.0% | -35.4pp → **-19.4pp** |
| OpenAI | gpt-2025-08 | 54.7% → 54.3% | 34.3% | -35.4pp → **-20.1pp** |
| xAI | xai-realtime | 54.7% → 54.3% | 37.7% | -24.4pp → **-16.6pp** |

### Against text\_sota (GPT-5 reasoning)

| Provider | Model | Text (old→new) | New Realistic | Gap (old→new) |
|----------|-------|---------------|--------------|--------------|
| Google | gemini | 80.0% → 84.7% | 24.6% | -55.5pp → -60.0pp |
| OpenAI | gpt-1.5 | 80.0% → 84.7% | 35.0% | -60.7pp → **-49.7pp** |
| OpenAI | gpt-2025-08 | 80.0% → 84.7% | 34.3% | -60.7pp → **-50.4pp** |
| xAI | xai-realtime | 80.0% → 84.7% | 37.7% | -49.7pp → **-46.9pp** |

**Key findings:**
- **Against GPT-4.1 (non-thinking), the gap narrowed dramatically** for all providers except Google. xAI's gap is now only 16.6pp (was 24.4pp). OpenAI's gap halved from 35.4pp to ~20pp.
- **Against GPT-5 (reasoning), the picture is mixed**: OpenAI's gap narrowed substantially (60.7pp → ~50pp) and xAI's narrowed slightly (49.7pp → 46.9pp), but Google's widened (55.5pp → 60.0pp). Overall range went from 50–61pp to 47–60pp.
- **xAI telecom still exceeds the non-thinking text baseline** (40.4% vs 34.0%), confirming this as the only domain where voice outperforms text.
- The choice of text reference point (thinking vs non-thinking) changes the narrative framing, but against both baselines, OpenAI and xAI are closing the gap while Google remains flat.

---

## 5. Ablation (Retail domain, single-factor)

### Pass@1 values by condition

| Condition | Google | gpt-1.5 | gpt-2025-08 | xAI | All Avg |
|-----------|--------|---------|-------------|-----|---------|
| Control | 38.6% | **69.3%** | 53.5% | 48.2% | 52.4% |
| +Audio | 35.1% (-3.5pp) | **64.9%** (-4.4pp) | 47.4% (-6.1pp) | 44.7% (-3.5pp) | 48.0% (-4.4pp) |
| +Accents | 45.6% (+7.0pp) | **58.8%** (-10.5pp) | 49.1% (-4.4pp) | 28.9% (-19.3pp) | 45.6% (-6.8pp) |
| +Behavior | 41.2% (+2.6pp) | **56.1%** (-13.2pp) | 45.6% (-7.9pp) | 50.9% (+2.6pp) | 48.5% (-3.9pp) |
| Realistic | 28.1% (-10.5pp) | **43.9%** (-25.4pp) | 33.3% (-20.2pp) | 36.8% (-11.4pp) | 35.5% (-16.9pp) |

### Comparison of single-factor deltas (old → new)

| Factor | Google (old→new) | OpenAI old → gpt-1.5 | OpenAI old → gpt-2025-08 | xAI (old→new) | Avg (old→new) |
|--------|-----------------|----------------------|--------------------------|--------------|--------------|
| Audio | -1.8pp → **-3.5pp** | -13.2pp → **-4.4pp** | -13.2pp → **-6.1pp** | -12.3pp → **-3.5pp** | -9.1pp → -4.4pp |
| Accents | -2.6pp → **+7.0pp** | -18.4pp → **-10.5pp** | -18.4pp → **-4.4pp** | -18.4pp → **-19.3pp** | -13.2pp → -6.8pp |
| Behavior | -0.9pp → **+2.6pp** | -8.8pp → **-13.2pp** | -8.8pp → **-7.9pp** | -5.3pp → **+2.6pp** | -5.0pp → -3.9pp |
| Realistic | -11.4pp → **-10.5pp** | -23.7pp → **-25.4pp** | -23.7pp → **-20.2pp** | -21.9pp → **-11.4pp** | -19.0pp → -16.9pp |

### Expected vs actual ordering

The intuitive expectation is **control ≥ single-factor ablations ≥ realistic** (adding complexity should only hurt). This holds on average, but breaks down for individual models:

| Model | Monotonic? | Violations |
|-------|-----------|------------|
| **gpt-1.5** | **Yes** | None. Clean ordering: control (69.3%) > audio (64.9%) > accents (58.8%) > behavior (56.1%) > realistic (43.9%) |
| **gpt-2025-08** | **Yes** | None. control (53.5%) > accents (49.1%) > audio (47.4%) > behavior (45.6%) > realistic (33.3%) |
| **Google** | **No** | **Accents (+7.0pp) and behavior (+2.6pp) both exceed control.** Only audio degrades. Adding diverse accents or user behaviors actually *helps* Google on retail. |
| **xAI** | **No** | **Behavior exceeds control** (+2.6pp). Also **realistic (36.8%) > accents-only (28.9%)** — the full combination of all factors produces *better* results than accents alone. |

Counter-intuitive patterns in detail:
- **Google with accents**: control\_accents (45.6%) is Google's *best* condition, 7pp above control (38.6%). Diverse accent personas may produce clearer or more deliberate speech that helps Google's model, or this could be statistical noise on 114 tasks.
- **Google and xAI with behavior**: Both improve with user behaviors (+2.6pp each). Interruptions, backchannels, and non-directed speech may paradoxically give the agent more time or contextual cues.
- **xAI: realistic > accents-only**: Accents alone devastate xAI (-19.3pp), but adding audio and behavior factors on top partially *compensates*, bringing realistic (36.8%) well above accents-only (28.9%). This suggests audio degradation and user behaviors may mask or soften the accent effect for xAI.

### Additivity analysis

Are the combined effects of all factors equal to the sum of individual effects?

| Model | Sum of individual deltas | Actual realistic delta | Interaction |
|-------|-------------------------|----------------------|-------------|
| Google | **+6.1pp** (net positive!) | **-10.5pp** | **Massively super-additive** — individual factors suggest improvement, but combined they degrade by 10.5pp |
| gpt-1.5 | -28.1pp | -25.4pp | Slightly sub-additive — combined is 2.7pp less bad than sum |
| gpt-2025-08 | -18.4pp | -20.2pp | Slightly super-additive — combined is 1.8pp worse than sum |
| xAI | -20.2pp | -11.4pp | **Massively sub-additive** — combined is 8.8pp less bad than sum (accents damage partially offset by other factors) |
| **All avg** | -15.1pp | -16.9pp | Slightly super-additive |

The extreme cases are **Google** (factors individually help, but combine catastrophically) and **xAI** (factors individually devastate via accents, but combine more mildly). This suggests complex interactions between speech complexity dimensions that differ fundamentally across models.

**Key findings:**
- **Accents remain the worst single factor on average** (-6.8pp), though halved from -13.2pp. It is **overwhelmingly an xAI problem** (-19.3pp) while Google actually *improves* with accents (+7.0pp) and gpt-2025-08 barely notices (-4.4pp).
- **Audio impact dramatically reduced** for all providers: average went from -9.1pp to -4.4pp. xAI improved the most (-12.3pp → -3.5pp).
- **Behavior has mixed effects**: Google (+2.6pp) and xAI (+2.6pp) actually improve slightly, while gpt-1.5 degrades significantly (-13.2pp).
- **gpt-1.5 has the largest Realistic degradation** (-25.4pp) despite having the highest absolute scores. This suggests the model's exceptional Clean performance is partially due to capabilities that are particularly vulnerable to speech complexity.
- **xAI's Realistic degradation halved** (-21.9pp → -11.4pp), mainly from improved audio and behavior robustness. Accent vulnerability persists (-19.3pp, slightly worse than old -18.4pp).
- **Both OpenAI models follow the expected monotonic pattern**; Google and xAI do not. The non-monotonicity is model-specific, not universal.

---

## 6. Impact on Paper Narrative

### Claims that still hold
- **A large voice-text gap remains**: Against GPT-5, the gap is 47–60pp. Against GPT-4.1, it is 17–30pp (xAI 16.6pp to Google 29.7pp). Either way, voice substantially lags text.
- **Realistic conditions degrade performance**: Clean→Realistic drops range from 4pp (Google) to 14pp (gpt-1.5, xAI).
- **No provider masters both task completion and conversational dynamics**: True — OpenAI has the best dynamics but worst selectivity.
- **xAI leads in both Clean and Realistic**: 50.7% Clean, 37.7% Realistic.
- **xAI dominates Telecom**: 57.9% Clean, 40.4% Realistic vs 20–28% for others.
- **Accents are the most damaging single factor on average** (-6.8pp), though mainly an xAI issue now.

### Claims that need significant revision

| Old Claim | New Reality |
|-----------|-------------|
| "19–30% under realistic conditions" | Now **25–38%** (wider range, higher ceiling) |
| "50–61pp gap from text [SOTA]" | Against GPT-5: **47–60pp** (narrowed for OpenAI/xAI, widened for Google). Against GPT-4.1: **17–30pp** (halved). Text baseline choice matters. |
| "Single OpenAI model" | **Two OpenAI models**: gpt-2025-08-28 (same model as old paper, renamed) + gpt-1.5 (new). Different task completion, similar voice dynamics |
| "OpenAI at 19% Realistic (worst)" | gpt-2025-08 (same model) now at **34.3%**, gpt-1.5 (new) at **35.0%** — both top-tier. gpt-2025-08 gain is from updated tasks, not model change |
| "Google shows smallest Clean→Realistic degradation" | **Google still smallest** at -4.3pp, but note Google also has the lowest absolute scores |
| "OpenAI slowest latency (2.22s)" | Now **fastest at 0.90s** (gpt-1.5) or 0.94s (gpt-2025-08) |
| "OpenAI highest selectivity (74%)" | Now **worst selectivity (6–7%)** — responds to everything |
| "OpenAI lowest responsiveness (68%)" | Now **highest responsiveness (99–100%)** |
| "Accents -13pp on average, universal problem" | Now **-6.8pp on average**, and mainly **an xAI problem** (-19pp). Google is unaffected (+7pp), both OpenAI models ≤ -10pp |
| "Google most robust in ablation" | Google still has smallest Realistic delta (-10.5pp), but **accents now help Google** (+7pp is unusual) |
| "Audio is second most damaging (-9pp)" | Now **-4.4pp** — audio robustness improved across the board |
| "Text baseline = GPT-4.1 (55%) / GPT-5 (80%)" | Baselines shifted: GPT-4.1 = **54.3%**, GPT-5 = **84.7%** (airline + retail tasks updated) |

### Provider characterization shift

**Old story (original paper):**
- Google = most robust, balanced conversational dynamics
- OpenAI = cautious/selective, worst latency, moderate task completion
- xAI = fastest/most responsive, best task completion, worst interruptions

**New story:**
- **Google** = stable anchor, smallest degradation (-4.3pp), balanced dynamics, but lowest absolute performance (~25–29%). Uniquely benefits from diverse accents (+7pp). Unchanged voice-text gap.
- **OpenAI** = **transformed** — two models with near-perfect responsiveness, sub-1s latency, but near-zero selectivity. gpt-1.5 (new model) achieves 48.5% Clean (near-xAI) and 35.0% Realistic. gpt-2025-08 (same model as old paper) also scores much higher on the updated tasks (40.7%/34.3%). Both respond to essentially all audio input including noise.
- **xAI** = still best in Clean (50.7%) and Realistic (37.7%), improved audio/behavior robustness, but accent vulnerability persists (-19pp) and is now the primary differentiator. Interruption rate improved (0.84 vs 1.05). Narrowest voice-text gap vs GPT-4.1 (16.6pp). Dominates telecom; exceeds text baseline there.

### Key tensions for the paper

1. **Two-model comparison complexity**: Having two OpenAI models changes the comparison structure. gpt-2025-08-28 is the same model as the old paper (renamed from `gpt-4o-realtime-preview`), while gpt-1.5 is genuinely new. The two share similar voice dynamics but differ in task completion (gpt-1.5: 48.5%/35.0% vs gpt-2025-08: 40.7%/34.3% overall).

2. **The OpenAI selectivity paradox**: Both OpenAI models respond to nearly everything (98% backchannels, 95% vocal tics, 86–90% non-directed speech) yet achieve top-tier task completion. This "respond to everything" strategy appears surprisingly effective for task completion while being poor conversational behavior.

3. **Text baseline framing**: The narrative depends critically on which text baseline is used. Against GPT-4.1 (non-thinking), voice is closing the gap (16.6pp for xAI). Against GPT-5 (reasoning), the gap is 47–60pp (narrowed for OpenAI/xAI, widened for Google). The paper should clearly frame which comparison is being made.

4. **Accents are now provider-specific**: Cannot frame accents as a universal problem. It's overwhelmingly an xAI issue (-19pp). Google actually benefits (+7pp). The accessibility concern still holds but is much more targeted.

5. **gpt-1.5's vulnerability paradox**: The strongest model in Clean (69.3% retail) has the largest degradation (-25.4pp retail). Being better at Clean doesn't protect against — and may amplify — speech complexity effects.

6. **Updated tasks**: Both airline and retail tasks were updated. Airline changes are large (text\_sota: 62.5% → 83.0%; all providers gained on control). Retail changes are smaller (text\_sota: 81.6% → 81.0%, text\_nonthinking: 74.0% → 76.0%). Direct comparison of results across paper versions requires acknowledging these task-set changes — especially for gpt-2025-08-28, where all performance differences are attributable to task changes since the model is the same.

