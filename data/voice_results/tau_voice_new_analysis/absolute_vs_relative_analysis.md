# Absolute vs Relative Impact Analysis

This document examines how absolute (pp) and relative (%) deltas tell different stories about the impact of speech complexity on voice agent performance.

**Definitions:**
- **Absolute delta**: `regular − control` (in percentage points). How many raw percentage points are gained or lost.
- **Relative delta**: `(regular − control) / control` (as %). What fraction of the Clean score is lost. A model at 60% that drops to 45% has an absolute delta of -15pp but a relative delta of -25%.

Relative deltas correct for baseline differences: a 10pp drop from 20% (-50% relative) is proportionally far more severe than a 10pp drop from 60% (-17% relative).

---

## 1. Clean → Realistic Degradation

### Overall (All domains)

| Provider | Model | Clean | Realistic | Abs. Δ | **Rel. Δ** |
|----------|-------|-------|-----------|--------|------------|
| Google | gemini | 28.9% | 24.6% | -4.3pp | **-14.9%** |
| OpenAI | gpt-2025-08 | 40.7% | 34.3% | -6.4pp | **-15.8%** |
| OpenAI | gpt-1.5 | 48.5% | 35.0% | -13.5pp | **-27.8%** |
| xAI | xai-realtime | 50.7% | 37.7% | -13.0pp | **-25.6%** |

**What absolute deltas say:** Google is the most robust (-4.3pp), far ahead of gpt-2025-08 (-6.4pp), with gpt-1.5 and xAI tied for worst (~-13pp).

**What relative deltas say:** Google and gpt-2025-08 are a **robustness cluster** (losing ~15% of Clean), while gpt-1.5 and xAI are a **vulnerability cluster** (losing ~26-28% of Clean). Google's apparent robustness advantage over gpt-2025-08 shrinks from 2.1pp to just 0.9 percentage points of relative degradation.

**Impact on the story:** The narrative shifts from "Google is uniquely robust" to "**Google and gpt-2025-08 are similarly robust in relative terms**, both losing about one-sixth of their Clean performance. gpt-1.5 and xAI lose about one-quarter." The robustness distinction is between two model tiers, not a single standout.

### Per domain

| Domain | Model | Clean | Abs. Δ | **Rel. Δ** | Abs. rank | **Rel. rank** |
|--------|-------|-------|--------|------------|-----------|---------------|
| **Retail** | Google | 38.6% | -10.5pp | -27.3% | 2nd | 2nd |
| | gpt-1.5 | 69.3% | -25.4pp | -36.7% | **4th (worst)** | 3rd |
| | gpt-2025-08 | 53.5% | -20.2pp | **-37.7%** | 3rd | **4th (worst)** |
| | xAI | 48.2% | -11.4pp | **-23.6%** | **1st (best)** | **1st (best)** |
| **Airline** | Google | 28.0% | +2.0pp | +7.1% | 1st | 1st |
| | gpt-1.5 | 48.0% | -8.0pp | -16.7% | 3rd | **2nd** |
| | gpt-2025-08 | 44.0% | 0.0pp | 0.0% | 2nd | 2nd |
| | xAI | 46.0% | -10.0pp | -21.7% | 4th | **4th** |
| **Telecom** | Google | 20.2% | -4.4pp | -21.7% | **1st (best)** | **2nd** |
| | gpt-1.5 | 28.1% | -7.0pp | -25.0% | 3rd | 3rd |
| | gpt-2025-08 | 24.6% | +0.9pp | +3.6% | tied 1st | 1st |
| | xAI | 57.9% | -17.5pp | -30.3% | 4th | 4th |

**Key ranking changes:**

1. **Retail: gpt-1.5 and gpt-2025-08 swap.** Absolute says gpt-1.5 is worst (-25.4pp). Relative says **gpt-2025-08 is worst (-37.7%)**, losing a larger fraction of its Clean score. gpt-1.5's bigger absolute drop is an artifact of starting from 69.3% vs 53.5%.

2. **Retail: xAI is most robust by both measures** (-11.4pp absolute, -23.6% relative). This is a cleaner finding — xAI is genuinely less affected by speech complexity in retail, not just starting from a lower baseline.

3. **Telecom: Google drops from 1st (absolute) to 2nd (relative).** Google's small absolute delta (-4.4pp) looks good, but relative to its very low Clean baseline (20.2%), it's losing 21.7% — worse than gpt-2025-08's +3.6%. Google's apparent telecom robustness is partly an artifact of having little to lose.

---

## 2. Voice vs Text Gap

### Against text\_sota (GPT-5)

| Provider | Model | Text | Voice (Realistic) | Abs. gap | **Rel. gap** | **Voice retains** |
|----------|-------|------|-------------------|----------|-------------|-------------------|
| Google | gemini | 84.7% | 24.6% | -60.0pp | -70.9% | **29.1%** |
| OpenAI | gpt-1.5 | 84.7% | 35.0% | -49.7pp | -58.7% | **41.3%** |
| OpenAI | gpt-2025-08 | 84.7% | 34.3% | -50.4pp | -59.5% | **40.5%** |
| xAI | xai-realtime | 84.7% | 37.7% | -46.9pp | -55.4% | **44.6%** |

**What absolute deltas say:** The gap ranges from 47–60pp. Google has the largest gap, xAI the smallest.

**What relative deltas say:** The same ranking, but expressed more intuitively as "what fraction of text capability survives in voice":
- **xAI retains 44.6%** of text SOTA performance
- **Both OpenAI models retain ~41%**
- **Google retains only 29.1%**

**Impact on the story:** The relative framing is more intuitive and more damning. Saying "voice agents retain 29–45% of text capability" is a clearer message than "the gap is 47–60pp." It also makes the provider spread more vivid: xAI keeps nearly half of text performance, Google less than a third.

### Per domain — what voice retains (% of text SOTA)

| Domain | Google | gpt-1.5 | gpt-2025-08 | xAI |
|--------|--------|---------|-------------|-----|
| Retail | 34.7% | **54.1%** | 41.2% | 45.4% |
| Airline | 36.1% | **48.2%** | **53.0%** | 43.4% |
| Telecom | **17.5%** | 23.4% | 28.3% | **44.8%** |

- **gpt-1.5 retains the most in retail (54.1%)** — over half of text capability survives voice. This is by far the best voice-to-text ratio in the benchmark.
- **gpt-2025-08 retains the most in airline (53.0%)** — again, over half. Recall this is the same model with 0pp degradation from Clean to Realistic in airline.
- **Telecom is where voice fails hardest**: Google retains only 17.5% of text capability. Even xAI, the telecom leader, retains less than half (44.8%).
- **xAI is the most consistent across domains**: retains 43–45% everywhere. Other models vary wildly (Google: 17–37%, gpt-1.5: 23–54%).

---

## 3. Ablation (Retail)

### Absolute vs relative single-factor deltas

| Factor | | Google | gpt-1.5 | gpt-2025-08 | xAI | Avg |
|--------|---|--------|---------|-------------|-----|-----|
| **Audio** | Abs. | -3.5pp | -4.4pp | -6.1pp | -3.5pp | -4.4pp |
| | **Rel.** | **-9.1%** | **-6.3%** | **-11.5%** | **-7.3%** | **-8.4%** |
| **Accents** | Abs. | +7.0pp | -10.5pp | -4.4pp | -19.3pp | -6.8pp |
| | **Rel.** | **+18.2%** | **-15.2%** | **-8.2%** | **-40.0%** | **-13.0%** |
| **Behavior** | Abs. | +2.6pp | -13.2pp | -7.9pp | +2.6pp | -3.9pp |
| | **Rel.** | **+6.8%** | **-19.0%** | **-14.8%** | **+5.5%** | **-7.5%** |
| **Realistic** | Abs. | -10.5pp | -25.4pp | -20.2pp | -11.4pp | -16.9pp |
| | **Rel.** | **-27.3%** | **-36.7%** | **-37.7%** | **-23.6%** | **-32.2%** |

**Key insights from relative deltas:**

1. **xAI's accent vulnerability is staggering**: -40.0% relative — accents alone wipe out **two-fifths** of xAI's Clean capability. This is by far the largest single-factor relative impact in the entire ablation. In absolute terms (-19.3pp), it was already the worst, but the relative framing makes the severity more vivid.

2. **gpt-1.5's behavior vulnerability stands out**: -19.0% relative, the second-largest single-factor relative impact after xAI accents. In absolute terms (-13.2pp) it was already notable, but relative to gpt-1.5's high baseline, it means nearly one-fifth of capability is lost from user behaviors alone.

3. **Audio is the most uniform factor**: All models lose 6–12% of Clean from audio, making it the most predictable and least provider-dependent degradation. Absolute deltas (3.5–6.1pp) are small, but relative deltas confirm this isn't just an artifact of different baselines.

4. **Google's accents anomaly is even more striking in relative terms**: +18.2% improvement. Google gains nearly a fifth of its Clean score from diverse accents. Whatever mechanism causes this (clearer enunciation, different speech patterns), it's a substantial proportional boost.

5. **Realistic degradation ranking flips between gpt-1.5 and gpt-2025-08**: In absolute terms, gpt-1.5 has the worst Realistic degradation (-25.4pp). In relative terms, **gpt-2025-08 is slightly worse (-37.7% vs -36.7%)**. Both OpenAI models lose over a third of their Clean retail performance, but the model with the lower baseline (gpt-2025-08) is proportionally more affected.

---

## 4. Summary: How Relative Deltas Change the Narrative

| Narrative claim (absolute) | Relative delta revision |
|---------------------------|------------------------|
| **"Google is the most robust model (-4.3pp)"** | Google and gpt-2025-08 are a **robustness cluster** (both ~15–16% loss). Google's advantage is marginal, not exceptional. |
| **"gpt-1.5 has the worst Realistic degradation (-25.4pp retail)"** | **gpt-2025-08 is slightly worse proportionally** (-37.7% vs -36.7%). gpt-1.5's larger absolute delta is an artifact of its higher Clean baseline. |
| **"xAI has the worst accent impact (-19.3pp)"** | Even more dramatic: **-40% relative**, wiping out two-fifths of Clean capability. The proportional severity is masked by the absolute number. |
| **"The voice-text gap is 47–60pp"** | Voice retains **29–45% of text capability**. More intuitive framing. xAI keeps nearly half; Google less than a third. |
| **"Google is most robust in telecom (-4.4pp)"** | Google loses 21.7% of an already-low baseline. **gpt-2025-08 (+3.6%) is actually more robust** — it slightly improves in telecom Realistic. |
| **"Degradation ranges from 4–14pp across providers"** | Proportionally, it ranges from **15–28%** — every model loses one-sixth to one-quarter of its Clean performance. The spread in relative terms (13pp range) is narrower than absolute (10pp range). |

### Recommended framing

The paper should present both absolute and relative deltas, as they answer different questions:

- **Absolute deltas** answer: "How many tasks flip from pass to fail?" — relevant for practical deployment impact.
- **Relative deltas** answer: "What fraction of capability is lost?" — relevant for understanding model robustness independent of baseline.

Key claims that should use relative deltas:
- Provider robustness comparisons (avoids penalizing high-performing models)
- Accent vulnerability severity (40% for xAI is more impactful than -19.3pp)
- Voice-text gap framing ("retains X% of text capability")
- Cross-model ablation comparisons (gpt-1.5 vs gpt-2025-08 in retail)

Key claims that should use absolute deltas:
- Overall Realistic score ranges ("25–38% under realistic conditions")
- Task-count interpretations ("13 more tasks fail under Realistic")
- Rankings by final Realistic performance (absolute scores determine real-world capability)
