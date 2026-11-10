# Scorer reference outputs

`flat/` is `../../scorer/baselines/flat.json` (P and Q frozen at their starting values) scored with `scorer/config_min.json`. Every score component is normalized so this model scores 1.0, so it is the check that normalization still holds after a scorer change. Score another reference model here with `scorer/score_submission.py ... --out results/scorer_reference/<name>`.
