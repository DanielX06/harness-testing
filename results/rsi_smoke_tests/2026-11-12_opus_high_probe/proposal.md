## evidence
If the composite is roughly the mean of TD, frequency response (FR) and droop, then FR + droop (3*composite - TD) is 1.0 to 1.8 even in runs that did not fail. That makes it the largest cost in every non-failed run; the averaged FR errors are 1.4 to 1.8 on three channels. The best runs (0e33 at 0.42, bc0c at 0.48, e561 at 0.45) are the ones whose coupling reactance ended large (3.86, 1.86, 0.6+Re). Runs that bounded XL to the documented 0.05–0.3 range (7aff, c08b, fa0b, 2d88, 7be1) have FR+droop around 1.5–1.8. I estimated the device's FR directly from the noise-free quiet recordings with an ARX model on differenced data. The estimate is consistent across files and units: |P/theta| is about 0.2 at 10 Hz, while XL=0.3 models give about 3. Run on the 20 part-2 submissions, the new tool's overall FR error follows the hidden FR+droop part: 0e33 0.95 (proxy 1.02), e561 1.16 (1.15), bc0c 1.25 (1.20), against 2d88 1.62 (1.82), fa0b 1.51 (1.78) and 7be1 1.51 (1.83). It takes about 1 s per call. Failures (4 of 20 runs) come mostly from models whose Q rises with V (194a, 4fb4, 429d) and from an angle init without theta0 (0e6c).

## root_cause
The solver has no way to see the scored FR. It picks among candidates by replay RMS alone, and it trusts the reference "normal ranges" as fitting bounds. Many runs therefore settle on stiff source-behind-small-XL models whose angle and voltage gains are several times the device's.

## change
I added tools/freq_response.py. It estimates the device's V/theta→P/Q frequency response from each quiet train recording, linearizes a submission at the same operating point, and prints both with a per-channel error. I rewrote method.md to run the tool at the start and on every candidate, to use wide bounds, to warn about positive dQ/dV (a regression of Q on V shows the grid's slope, not the device's), and to require theta0 in angle inits.

## predicted_effect
The FR channel errors (currently 1.4–1.8) should fall toward about 1. That would lower the composite by roughly 0.1–0.2 on both units. A few failures should also be avoided through the dQ/dV and theta0 notes.

## at_risk
Haiku may spend calls on the extra tool and run out of steps. It may over-chase FR at the cost of TD. The ARX estimate is rough below 0.2 Hz. On a future unit with a stiff response, the advice to widen bounds is harmless, but the tool's numbers only help if that unit's quiet recordings excite it.