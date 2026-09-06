# Evaluation Report

This report evaluates the performance of the Prototype Access-Instruction system against the Baseline (no-memory) system. The results are based on a 90-day simulation of 1000 deliveries across 200 synthetic addresses.

## Quantitative Metrics

| Metric | Baseline | Target | Measured Prototype | Error Analysis |
|---|---|---|---|---|
| **Repeat Failure Rate** | 51.3% | <40% | **36.3%** | The prototype successfully dropped repeat failures below the target. The remaining 36.3% is largely due to our simulated "gate code changes" (which intentionally broke some notes midway through) and natural difficulty baselines. |
| **Reliability** | 56.7% | >70% | **71.4%** | First-attempt success rate improved significantly. The target was met. |
| **Cost per Success** | Rs.70.55 | <Rs.60 | **Rs.56.02** | By drastically reducing wasted "failed" trips to difficult addresses, the cost to achieve one successful delivery fell by ~20%, surpassing the target. |
| **Emissions** | 420.0 kg | (Constant) | **420.0 kg** | *Note*: Since the simulation ran a fixed 1000 attempts for both, the total emissions are identical. A better operational metric would be "Emissions per successful delivery", which decreased proportionally with the Cost metric. |
| **RTO Rate** | 7.7% | <6.0% | **6.5%** | RTO rate dropped, but missed the aggressive 6.0% target. This is likely because the simulation's RTO logic applies a flat 20% conversion rate to all failures, meaning natural baseline failures still leak into RTOs. |

## The "No False Precision" Requirement

The system successfully avoids false precision by strictly outputting confidence bands instead of raw percentages to the driver. 

**Example Dispatch Responses:**

1. **New Note (1 confirmation)**
   - *Score*: `0.50`
   - *Shown to Driver*: `Medium confidence — may be outdated`
   - *Why?*: Because a single driver's success doesn't guarantee the note is robust. It needs more validation.

2. **Highly Confirmed Note (3 confirmations, recent)**
   - *Score*: `0.80`
   - *Shown to Driver*: `High confidence — confirmed recently`
   - *Why?*: Multiple drivers have successfully used this note in the last few days.

3. **Stale Note (3 confirmations, but 2 recent failures)**
   - *Score*: `0.57`
   - *Shown to Driver*: `Medium confidence — may be outdated`
   - *Why?*: The contradiction count mathematically drags down the high confirmation count, warning the driver that something might have changed (e.g. gate code rotated).

4. **Cold Start (0 notes)**
   - *Score*: `None`
   - *Shown to Driver*: `Low confidence / no verified note — attempt as new address`
   - *Why?*: Explicitly stating the lack of data is critical so dispatch systems do not conflate a blank field with "no access barrier exists".
