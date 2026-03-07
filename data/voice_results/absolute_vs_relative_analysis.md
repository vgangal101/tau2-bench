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
| OpenAI | gpt-1.5 | 48.5% | 35.0% | -13.5pp | **-27.8%** |
| xAI | xai-realtime | 50.7% | 37.7% | -13.0pp | **-25.6%** |

**What absolute deltas say:** Google is by far the most robust (-4.3pp), with xAI and gpt-1.5 tied for worst (~-13pp). A 3× gap separates Google from the other two.

**What relative deltas say:** The gap narrows. Google still leads at -14.9%, but **the difference between Google and the others is a 2× factor, not 3×**. gpt-1.5 (-27.8%) and xAI (-25.6%) both lose about a quarter of their Clean performance — but relative to their much higher baselines (49–51% vs Google's 29%), the proportional impact is less extreme than the absolute numbers suggest.

**Impact on the story:** Google is genuinely the most robust by both measures. But the absolute framing overstates the gap: Google's small absolute delta is partly an artifact of having less to lose. The more honest framing is "Google loses one-seventh, others lose one-quarter."

### Per domain

| Domain | Model | Clean | Abs. Δ | **Rel. Δ** | Abs. rank | **Rel. rank** |
|--------|-------|-------|--------|------------|-----------|---------------|
| **Retail** | Google | 38.6% | -10.5pp | -27.3% | 2nd | 2nd |
| | gpt-1.5 | 69.3% | -25.4pp | -36.7% | 3rd (worst) | 3rd (worst) |
| | xAI | 48.2% | -11.4pp | -23.6% | 1st (best) | 1st (best) |
| **Airline** | Google | 28.0% | +2.0pp | +7.1% | 1st | 1st |
| | gpt-1.5 | 48.0% | -8.0pp | -16.7% | 2nd | 2nd |
| | xAI | 46.0% | -10.0pp | -21.7% | 3rd | 3rd |
| **Telecom** | Google | 20.2% | -4.4pp | -21.7% | 1st (best) | 1st (best) |
| | gpt-1.5 | 28.1% | -7.0pp | -25.0% | 2nd | 2nd |
| | xAI | 57.9% | -17.5pp | -30.3% | 3rd (worst) | 3rd (worst) |

**Key observations:**

1. **Rankings are perfectly consistent across all domains.** Unlike the previous analysis (which included gpt-2025-08), removing that model eliminates all ranking swaps between absolute and relative measures. The relative ordering of Google > gpt-1.5 > xAI (in terms of robustness) or xAI > Google > gpt-1.5 (retail) is the same whether measured absolutely or relatively.

2. **Retail: xAI is most robust by both measures** (-11.4pp absolute, -23.6% relative). gpt-1.5 is worst by both — its massive 25.4pp absolute drop is also the largest proportional loss (-36.7%), losing over a third of its Clean capability. gpt-1.5's high baseline (69.3%) does not protect it; if anything it amplifies vulnerability.

3. **Telecom: the relative lens exposes Google's fragility.** Google's small absolute delta (-4.4pp) keeps it at #1 in robustness, but relative to its very low Clean baseline (20.2%), it's still losing 21.7% — not far from gpt-1.5's 25.0%. Google's apparent telecom robustness is partly an artifact of having little to lose.

4. **xAI is always the least robust relative to its baseline.** In retail (-23.6%), airline (-21.7%), and telecom (-30.3%), xAI consistently loses the most proportionally. This is hidden in the absolute view where xAI looks comparable to Google in retail and airline.

---

## 2. Voice vs Text Gap

### Against text\_sota (GPT-5)

| Provider | Model | Text | Voice (Realistic) | Abs. gap | **Rel. gap** | **Voice retains** |
|----------|-------|------|-------------------|----------|-------------|-------------------|
| Google | gemini | 84.7% | 24.6% | -60.0pp | -70.9% | **29.1%** |
| OpenAI | gpt-1.5 | 84.7% | 35.0% | -49.7pp | -58.7% | **41.3%** |
| xAI | xai-realtime | 84.7% | 37.7% | -46.9pp | -55.4% | **44.6%** |

**What absolute deltas say:** The gap ranges from 47–60pp. Google has the largest gap, xAI the smallest, OpenAI in between.

**What relative deltas say:** The same ranking, expressed more intuitively as "what fraction of text capability survives in voice":
- **xAI retains 44.6%** of text SOTA performance
- **OpenAI gpt-1.5 retains 41.3%**
- **Google retains only 29.1%**

**Impact on the story:** The relative framing is more intuitive and more damning. Saying "voice agents retain 29–45% of text capability" is a clearer message than "the gap is 47–60pp." It also makes the provider spread more vivid: xAI keeps nearly half of text performance, Google less than a third.

### Per domain — what voice retains (% of text SOTA)

| Domain | Google | gpt-1.5 | xAI |
|--------|--------|---------|-----|
| Retail | 34.7% | **54.1%** | 45.4% |
| Airline | 36.1% | **48.2%** | 43.4% |
| Telecom | **17.5%** | 23.4% | **44.8%** |

- **gpt-1.5 retains the most in retail (54.1%)** — over half of text capability survives voice. This is by far the best voice-to-text ratio in the benchmark.
- **Telecom is where voice fails hardest**: Google retains only 17.5% of text capability. Even xAI, the telecom leader, retains less than half (44.8%).
- **xAI is the most consistent across domains**: retains 43–45% everywhere. Other models vary wildly (Google: 17–37%, gpt-1.5: 23–54%).

---

## 3. Ablation (Retail)

### Absolute vs relative single-factor deltas

| Factor | | Google | gpt-1.5 | xAI | Avg |
|--------|---|--------|---------|-----|-----|
| **Audio** | Abs. | -3.5pp | -4.4pp | -3.5pp | -3.8pp |
| | **Rel.** | **-9.1%** | **-6.3%** | **-7.3%** | **-7.3%** |
| **Accents** | Abs. | +7.0pp | -10.5pp | -19.3pp | -7.6pp |
| | **Rel.** | **+18.2%** | **-15.2%** | **-40.0%** | **-14.6%** |
| **Behavior** | Abs. | +2.6pp | -13.2pp | +2.6pp | -2.6pp |
| | **Rel.** | **+6.8%** | **-19.0%** | **+5.5%** | **-5.1%** |
| **Realistic** | Abs. | -10.5pp | -25.4pp | -11.4pp | -15.8pp |
| | **Rel.** | **-27.3%** | **-36.7%** | **-23.6%** | **-30.3%** |

**Key insights from relative deltas:**

1. **xAI's accent vulnerability is staggering**: -40.0% relative — accents alone wipe out **two-fifths** of xAI's Clean capability. This is by far the largest single-factor relative impact in the entire ablation. In absolute terms (-19.3pp), it was already the worst, but the relative framing makes the severity more vivid.

2. **gpt-1.5's behavior vulnerability stands out**: -19.0% relative, the second-largest single-factor relative impact after xAI accents. In absolute terms (-13.2pp) it was already notable, but relative to gpt-1.5's high baseline, it means nearly one-fifth of capability is lost from user behaviors alone.

3. **Audio is the most uniform factor**: All models lose 6–9% of Clean from audio, making it the most predictable and least provider-dependent degradation. Absolute deltas (3.5–4.4pp) are also tight. Both measures agree: audio is a small, consistent tax.

4. **Google's accents anomaly is even more striking in relative terms**: +18.2% improvement. Google gains nearly a fifth of its Clean score from diverse accents. Whatever mechanism causes this (clearer enunciation, different speech patterns), it's a substantial proportional boost.

5. **Behavior is the most polarized factor**: gpt-1.5 loses 19% of Clean from behaviors, while Google and xAI each gain ~6%. This three-way split — one model devastated, two models improved — is unique to the behavior factor.

---

## 4. Summary: How Relative Deltas Change the Narrative

| Narrative claim (absolute) | Relative delta revision |
|---------------------------|------------------------|
| **"Google is the most robust model (-4.3pp)"** | True, but overstated. Google loses 14.9% vs 26–28% for others — a **2× gap, not 3×**. Part of Google's small absolute delta is having less to lose. |
| **"gpt-1.5 and xAI are equally vulnerable (~-13pp)"** | Not quite: xAI is slightly more robust relatively (-25.6% vs -27.8%). But the difference is small — both lose about a quarter. |
| **"gpt-1.5 has the worst Realistic degradation (-25.4pp retail)"** | Confirmed in both measures: -36.7% relative is also worst. Unlike the previous analysis with gpt-2025-08, there is no ranking flip. High baseline does not protect gpt-1.5. |
| **"xAI has the worst accent impact (-19.3pp)"** | Even more dramatic: **-40% relative**, wiping out two-fifths of Clean capability. The proportional severity exceeds the absolute impression. |
| **"The voice-text gap is 47–60pp"** | Voice retains **29–45% of text capability**. More intuitive framing. xAI keeps nearly half; Google less than a third. |
| **"Google is most robust in telecom (-4.4pp)"** | True absolutely, but Google's 21.7% relative loss is not far from gpt-1.5's 25.0%. Google's robustness is partly an artifact of its 20.2% Clean baseline. |
| **"Degradation ranges from 4–14pp across providers"** | Proportionally, it ranges from **15–28%** — every model loses one-seventh to one-quarter of its Clean performance. |

### Key finding: rankings are stable

With three models (removing gpt-2025-08), **absolute and relative rankings agree in every domain**. There are no ranking swaps. This makes the narrative cleaner: Google is most robust, xAI leads on absolute Realistic, and gpt-1.5 has both the highest Clean and the largest proportional losses.

### Recommended framing

The paper should present both absolute and relative deltas, as they answer different questions:

- **Absolute deltas** answer: "How many tasks flip from pass to fail?" — relevant for practical deployment impact.
- **Relative deltas** answer: "What fraction of capability is lost?" — relevant for understanding model robustness independent of baseline.

Key claims that should use relative deltas:
- Provider robustness comparisons (clarifies that Google's advantage is 2×, not 3×)
- Accent vulnerability severity (40% for xAI is more impactful than -19.3pp)
- Voice-text gap framing ("retains X% of text capability")
- xAI cross-domain consistency (retains 43–45% everywhere)

Key claims that should use absolute deltas:
- Overall Realistic score ranges ("25–38% under realistic conditions")
- Task-count interpretations ("13 more tasks fail under Realistic")
- Rankings by final Realistic performance (absolute scores determine real-world capability)
- gpt-1.5's retail dominance (69.3% Clean, 43.9% Realistic — absolute numbers tell the success story)
