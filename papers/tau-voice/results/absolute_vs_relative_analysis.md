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
| Google | gemini | 30.7% | 25.2% | -5.5pp | **-17.8%** |
| OpenAI | gpt-1.5 | 48.5% | 35.0% | -13.5pp | **-27.8%** |
| xAI | xai-realtime | 50.7% | 37.7% | -13.0pp | **-25.6%** |

**What absolute deltas say:** Google is the most robust (-5.5pp), with xAI and gpt-1.5 tied for worst (~-13pp). A 2.4× gap separates Google from the other two.

**What relative deltas say:** The gap narrows further. Google still leads at -17.8%, but **the difference between Google and the others is a 1.5× factor, not 2.4×**. gpt-1.5 (-27.8%) and xAI (-25.6%) both lose about a quarter of their Clean performance — but relative to their higher baselines (49–51% vs Google's 31%), the proportional impact is less extreme than the absolute numbers suggest.

**Impact on the story:** Google is genuinely the most robust by both measures. But the absolute framing overstates the gap: Google's small absolute delta is partly an artifact of having less to lose. The more honest framing is "Google loses one-sixth, others lose one-quarter." The robustness advantage is real but is ~1.5× rather than ~2.5×.

**Change from intermediate:** Google's relative delta worsened from -14.9% to -17.8% (its Clean baseline rose from 29% to 31%, but its Realistic delta also grew from -4.3pp to -5.5pp). The robustness advantage narrowed: was 2× (15% vs 26–28%), now ~1.5× (18% vs 26–28%).

### Per domain

| Domain | Model | Clean | Abs. Δ | **Rel. Δ** | Abs. rank | **Rel. rank** |
|--------|-------|-------|--------|------------|-----------|---------------|
| **Retail** | Google | 43.9% | -14.0pp | -32.0% | 3rd (worst) | 2nd |
| | gpt-1.5 | 69.3% | -25.4pp | -36.7% | 3rd (worst) | 3rd (worst) |
| | xAI | 48.2% | -11.4pp | -23.6% | 1st (best) | 1st (best) |
| **Airline** | Google | 28.0% | +2.0pp | +7.1% | 1st | 1st |
| | gpt-1.5 | 48.0% | -8.0pp | -16.7% | 2nd | 2nd |
| | xAI | 46.0% | -10.0pp | -21.7% | 3rd | 3rd |
| **Telecom** | Google | 20.2% | -4.4pp | -21.7% | 1st (best) | 1st (best) |
| | gpt-1.5 | 28.1% | -7.0pp | -25.0% | 2nd | 2nd |
| | xAI | 57.9% | -17.5pp | -30.3% | 3rd (worst) | 3rd (worst) |

**Key observations:**

1. **Retail rankings swap between absolute and relative.** Google is worst absolutely (-14.0pp) but second relatively (-32.0% vs gpt-1.5's -36.7%). This is a ranking flip: absolute says Google is worst in retail, relative says gpt-1.5 is worst. This is the only domain where absolute and relative rankings diverge.

2. **Retail: xAI is most robust by both measures** (-11.4pp absolute, -23.6% relative). gpt-1.5 is worst by both measures in relative terms — its massive 25.4pp absolute drop is also the largest proportional loss (-36.7%), losing over a third of its Clean capability.

3. **Telecom: the relative lens exposes Google's fragility.** Google's small absolute delta (-4.4pp) keeps it at #1 in robustness, but relative to its very low Clean baseline (20.2%), it's still losing 21.7% — not far from gpt-1.5's 25.0%. Google's apparent telecom robustness is partly an artifact of having little to lose.

4. **Google's retail vulnerability is new.** In the intermediate data, Google's retail delta was -10.5pp (-27.3% relative) — 2nd place. Now at -14.0pp (-32.0%), Google is the worst absolutely and second-worst relatively. Google's improved retail Clean (39%→44%) came with larger degradation.

---

## 2. Voice vs Text Gap

### Against text\_sota (GPT-5)

| Provider | Model | Text | Voice (Realistic) | Abs. gap | **Rel. gap** | **Voice retains** |
|----------|-------|------|-------------------|----------|-------------|-------------------|
| Google | gemini | 84.7% | 25.2% | -59.5pp | -70.2% | **29.8%** |
| OpenAI | gpt-1.5 | 84.7% | 35.0% | -49.7pp | -58.7% | **41.3%** |
| xAI | xai-realtime | 84.7% | 37.7% | -46.9pp | -55.4% | **44.6%** |

**What absolute deltas say:** The gap ranges from 47–59pp. Google has the largest gap, xAI the smallest, OpenAI in between.

**What relative deltas say:** The same ranking, expressed more intuitively as "what fraction of text capability survives in voice":
- **xAI retains 44.6%** of text SOTA performance
- **OpenAI gpt-1.5 retains 41.3%**
- **Google retains only 29.8%** — just under a third

**Impact on the story:** The relative framing is more intuitive and more damning. Saying "voice agents retain 30–45% of text capability" is a clearer message than "the gap is 47–59pp." It also makes the provider spread more vivid: xAI keeps nearly half of text performance, Google less than a third.

**Change from intermediate:** Google retains slightly more (29.1%→29.8%) due to improved retail Realistic. The overall range shifts from "29–45%" to "30–45%".

### Per domain — what voice retains (% of text SOTA)

| Domain | Google | gpt-1.5 | xAI |
|--------|--------|---------|-----|
| Retail | **36.8%** | **54.1%** | 45.5% |
| Airline | 36.1% | **48.2%** | 43.4% |
| Telecom | **17.5%** | 23.4% | **44.8%** |

- **gpt-1.5 retains the most in retail (54.1%)** — over half of text capability survives voice. This is by far the best voice-to-text ratio in the benchmark.
- **Telecom is where voice fails hardest**: Google retains only 17.5% of text capability. Even xAI, the telecom leader, retains less than half (44.8%).
- **xAI is the most consistent across domains**: retains 43–45% everywhere. Other models vary wildly (Google: 17–37%, gpt-1.5: 23–54%).
- **Google improved in retail** (34.7%→36.8%) due to higher Realistic score.

---

## 3. Ablation (Retail)

### Absolute vs relative single-factor deltas

| Factor | | Google | gpt-1.5 | xAI | Avg |
|--------|---|--------|---------|-----|-----|
| **Audio** | Abs. | -3.5pp | -4.4pp | -3.5pp | -3.8pp |
| | **Rel.** | **-8.0%** | **-6.3%** | **-7.3%** | **-7.1%** |
| **Accents** | Abs. | -0.9pp | -10.5pp | -19.3pp | -10.2pp |
| | **Rel.** | **-2.0%** | **-15.2%** | **-40.0%** | **-19.0%** |
| **Behavior** | Abs. | -10.5pp | -13.2pp | +2.6pp | -7.0pp |
| | **Rel.** | **-24.0%** | **-19.0%** | **+5.5%** | **-13.0%** |
| **Realistic** | Abs. | -14.0pp | -25.4pp | -11.4pp | -17.0pp |
| | **Rel.** | **-32.0%** | **-36.7%** | **-23.6%** | **-31.5%** |

**Key insights from relative deltas:**

1. **xAI's accent vulnerability is staggering**: -40.0% relative — accents alone wipe out **two-fifths** of xAI's Clean capability. This is by far the largest single-factor relative impact in the entire ablation. In absolute terms (-19.3pp), it was already the worst, but the relative framing makes the severity more vivid.

2. **Google's behavior vulnerability is the second-largest relative impact**: -24.0% — nearly a quarter of Google's Clean capability lost from user behaviors alone. In absolute terms (-10.5pp) this is already severe, and relatively it's comparable to gpt-1.5's -19.0%.

3. **gpt-1.5's behavior vulnerability stands out**: -19.0% relative. In absolute terms (-13.2pp) it's the worst, but relatively Google is now worse (-24.0%). This is because Google's lower Clean baseline (43.9% vs 69.3%) amplifies the proportional impact.

4. **Audio is the most uniform factor**: All models lose 6–8% of Clean from audio, making it the most predictable and least provider-dependent degradation. Absolute deltas (3.5–4.4pp) are also tight. Both measures agree: audio is a small, consistent tax.

5. **Accents are nearly invisible for Google**: -2.0% relative, essentially noise. This contrasts sharply with the intermediate results where Google *gained* 18.2%. The final data shows Google is simply neutral to accents, not helped by them.

6. **Behavior is the most polarized factor**: Google (-24%) and gpt-1.5 (-19%) are severely hurt, while xAI gains (+5.5%). This two-against-one split — two models devastated, one model improved — makes behavior the most provider-dependent factor.

**Change from intermediate:** The relative deltas for Google shifted dramatically:
- Accents: +18.2% → **-2.0%** (was Google's best condition, now neutral)
- Behavior: +6.8% → **-24.0%** (was mild help, now severe hurt)
- Audio: -9.1% → -8.0% (similar)
- Realistic: -27.3% → -32.0% (worse)

---

## 4. Summary: How Relative Deltas Change the Narrative

| Narrative claim (absolute) | Relative delta revision |
|---------------------------|------------------------|
| **"Google is the most robust model (-5.5pp)"** | True, but the advantage is smaller than it looks. Google loses 17.8% vs 26–28% for others — a **1.5× gap, not 2.5×**. Part of Google's small absolute delta is having less to lose. |
| **"gpt-1.5 and xAI are equally vulnerable (~-13pp)"** | Not quite: xAI is slightly more robust relatively (-25.6% vs -27.8%). But the difference is small — both lose about a quarter. |
| **"gpt-1.5 has the worst Realistic degradation (-25.4pp retail)"** | Confirmed in both measures: -36.7% relative is also worst. High baseline does not protect gpt-1.5. |
| **"xAI has the worst accent impact (-19.3pp)"** | Even more dramatic: **-40% relative**, wiping out two-fifths of Clean capability. The proportional severity exceeds the absolute impression. |
| **"Google is most hurt by behavior (-10.5pp)"** | Confirmed and even starker relatively: **-24.0%** — Google loses nearly a quarter of its Clean score from behaviors. This is a bigger proportional hit than gpt-1.5's -19.0%, despite gpt-1.5's larger absolute loss (-13.2pp). |
| **"The voice-text gap is 47–59pp"** | Voice retains **30–45% of text capability**. More intuitive framing. xAI keeps nearly half; Google just under a third. |
| **"Google is most robust in telecom (-4.4pp)"** | True absolutely, but Google's 21.7% relative loss is not far from gpt-1.5's 25.0%. Google's robustness is partly an artifact of its 20.2% Clean baseline. |
| **"Degradation ranges from 5–13pp across providers"** | Proportionally, it ranges from **18–28%** — every model loses one-sixth to one-quarter of its Clean performance. |
| **"Retail: Google is worst absolutely (-14.0pp)"** | Relatively, gpt-1.5 is worst (-36.7% vs Google's -32.0%). This is the **one ranking flip** — absolute and relative disagree on who is worst in retail. |

### Key finding: one ranking flip in retail

With the final data, absolute and relative rankings agree in airline and telecom but **diverge in retail**: Google is worst absolutely (-14.0pp) but gpt-1.5 is worst relatively (-36.7%). This matters for framing: "Google suffers the largest retail drop" (absolute, deployment focus) vs "gpt-1.5 loses the largest fraction of its retail capability" (relative, robustness focus).

### Recommended framing

The paper should present both absolute and relative deltas, as they answer different questions:

- **Absolute deltas** answer: "How many tasks flip from pass to fail?" — relevant for practical deployment impact.
- **Relative deltas** answer: "What fraction of capability is lost?" — relevant for understanding model robustness independent of baseline.

Key claims that should use relative deltas:
- Provider robustness comparisons (clarifies that Google's advantage is ~1.5×, not ~2.5×)
- Accent vulnerability severity (40% for xAI is more impactful than -19.3pp)
- Voice-text gap framing ("retains X% of text capability")
- Behavior vulnerability (Google's -24% is proportionally worse than gpt-1.5's -19%)
- xAI cross-domain consistency (retains 43–45% everywhere)

Key claims that should use absolute deltas:
- Overall Realistic score ranges ("25–38% under realistic conditions")
- Task-count interpretations ("14 more tasks fail under Realistic" for Google)
- Rankings by final Realistic performance (absolute scores determine real-world capability)
- gpt-1.5's retail dominance (69.3% Clean, 43.9% Realistic — absolute numbers tell the success story)
