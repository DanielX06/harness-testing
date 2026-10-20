"""Score a symbolic terminal-model submission, closed loop, on held-out grids.

    python score.py submission.json [--config config_min.json] [--out DIR] [--workers N]

For every held-out run on every grid, the submitted model replaces the device in the ANDES
network, the same disturbance is applied, and the device's terminal P and Q are compared with
the clean recording. The submission is JSON (equations as strings) and is never executed, so no
sandbox is needed; ANDES runs in parallel worker processes.

Per grid:  score = w_td * TD + w_fr * FR + w_par * PAR, each component capped at 2
           (flat prediction = 1.0 on every component, perfect = 0, failure = 2)
Per role:  (1 - w) * mean + w * worst over that role's grids
Writes DIR/public.json (selection grids only, what the updater may see) and DIR/private.json,
and DIR/andes/ (private): an ANDES log per simulation, plus the last DEBUG lines (*.debug.log,
gitignored) and the trajectory up to the failure (*_partial.npz) for every simulation that failed.
"""
import argparse
import json
import os
import shutil
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import closedloop as CL                               # noqa: E402
import metrics as M                                   # noqa: E402
import symbolic                                       # noqa: E402
from cases import load_config                         # noqa: E402


def _freq_refs(lin, S):
    f = np.logspace(np.log10(S["fr"]["f_min"]), np.log10(S["fr"]["f_max"]), S["fr"]["n"])
    mats = [lin[k] for k in "ABCD"]
    gains, conv = M.droop_gains(*mats, f_lo=S["droop"]["f_lo_hz"])
    return M.transfer(*mats, f), gains, conv


def truth_refs(g, S):
    G, gains, conv = _freq_refs(symbolic.Model(g.truth_spec).linearize(g.op), S)
    if any(v is None for v in gains.values()):
        raise RuntimeError(f"{g.name}: truth droop gains did not converge {conv}")
    return G, gains


def _fail_all(grids, kind, detail):
    entry = {"score": M.FAIL, "td": M.FAIL, "fr": M.FAIL, "par": M.FAIL,
             "failures": [{"task": "submission", "failure": kind, "detail": detail[-600:]}]}
    return [(g, M.FAIL, entry, {**entry, "role": g.role}) for g in grids]


def score_grid(g, S, m, results):
    fails = []
    td_runs, extra = {}, {}
    for r in g.runs:
        res = results[f"{g.name}__{r.id}"]
        if res["ok"]:
            n = min(len(res["P"]), len(r.t))
            Yp = np.column_stack([res["P"][:n], res["Q"][:n]])
            Yt = np.column_stack([r.Y["P"][:n], r.Y["Q"][:n]])
            td_runs[r.id] = M.td_run_error(Yp, Yt, g.sigma, S["td"]["floor_sigmas"])
            extra[r.id] = {**{f"rmse_{k}": float(np.sqrt(np.mean((res[k][:n] - r.Y[k][:n]) ** 2)))
                              for k in ("V", "theta")}, "seconds": round(res["seconds"], 1)}
        else:
            td_runs[r.id] = {"P": M.FAIL, "Q": M.FAIL, "failure": res["failure"]}
            fails.append({"task": r.id, "failure": res["failure"], "detail": res.get("detail", "")})
    td = float(np.mean([v[c] for v in td_runs.values() for c in ("P", "Q")]))

    G_true, gains_true = truth_refs(g, S)
    lin_info = {}
    try:
        lin = m.linearize(g.op)
        G, gains, conv = _freq_refs(lin, S)
        if not np.all(np.isfinite(G)):
            raise ValueError("non-finite frequency response")
        fr_detail = M.fr_error(G, G_true, S["fr"]["floor_frac"])
        fr = fr_detail["mean"]
        lin_info = {"n_states": int(lin["A"].shape[0]), "init_residual": lin["init_residual"],
                    "init_output_mismatch": lin["init_output_mismatch"],
                    "max_real_eig_open_loop": float(np.max(np.linalg.eigvals(lin["A"]).real))
                    if lin["A"].size else None, "droop_convergence": conv}
        for k, v in gains.items():
            if v is None:
                fails.append({"task": f"droop_{k}", "failure": "no_steady_gain",
                              "detail": "low-frequency gain did not converge (no droop, or a pure integrator)"})
    except Exception as e:
        fr, fr_detail, gains = M.FAIL, {"failure": "linearize"}, {}
        fails.append({"task": "linearize", "failure": "crash", "detail": f"{type(e).__name__}: {e}"[-400:]})
    par_detail = M.par_error(gains, gains_true)
    par = par_detail["mean"]

    W = S["weights"]
    score = float(W["td"] * td + W["fr"] * fr + W["par"] * par)
    f_nom = g.meta.get("nominal_frequency_Hz", 60.0)
    public = {"score": round(score, 4), "td": round(td, 4), "fr": round(fr, 4), "par": round(par, 4),
              "td_runs": {k: {"P": round(v["P"], 4), "Q": round(v["Q"], 4),
                              **({"failure": v["failure"]} if "failure" in v else {})}
                          for k, v in td_runs.items()},
              "fr_entries": {k: round(v, 4) for k, v in fr_detail.items() if k not in ("mean", "failure")},
              "par_entries": {k: round(par_detail[k], 4) for k in ("freq", "volt")},
              "failures": [{"task": x["task"], "failure": x["failure"], "detail": x["detail"][-300:]}
                           for x in fails]}
    private = {**public, "role": g.role, "td_runs_full": td_runs, "terminal_errors": extra,
               "fr_detail": fr_detail, "par_detail": par_detail,
               "droop_submission": M.readable(gains, f_nom), "droop_truth": M.readable(gains_true, f_nom),
               "gains_submission": gains, "gains_truth": gains_true, "linearization": lin_info}
    return score, public, private


def score_submission(submission, config_path, n_workers=None, log_dir=None):
    """log_dir: where each simulation's ANDES log (and, for a failure, its partial trajectory) goes.
    Private: give it a folder beside private.json, never one the loop reads."""
    cfg, grids = load_config(config_path)
    S = {k: v for k, v in cfg.items() if k != "grids"}
    w = time.monotonic()
    text = open(submission).read()
    structure = None
    try:
        spec = json.loads(text)
        m = symbolic.Model(spec)
        structure = {"states": m.state_names, "params": m.params, "n_defs": len(m.defs)}
    except (json.JSONDecodeError, symbolic.SubmissionError) as e:
        return _wrap(_fail_all(grids, "invalid_submission", str(e)), S, submission, structure, w, error=str(e))

    canon = json.dumps(spec)                   # keeps key order: defs are sequential
    cls = CL.class_name(canon)
    pycode = None
    try:
        try:
            CL.register(m, cls)
            pycode = CL.job_pycode()
            CL.generate_code(pycode)
        except Exception as e:
            return _wrap(_fail_all(grids, "codegen", f"{type(e).__name__}: {e}"), S, submission, structure, w,
                         error=str(e))
        finally:
            CL.unregister(cls)
        tasks = [{"id": f"{g.name}__{r.id}", "builder": g.builder, "run": r.id, "grid_spec": g.spec_text,
                  "tf": float(r.t[-1]), "tstep": float(r.t[1] - r.t[0]), "log_dir": log_dir}
                 for g in grids for r in g.runs]
        results = CL.run_many(tasks, canon, cls, pycode, n_workers=n_workers, timeout_s=S["run_timeout_s"])
    finally:
        if pycode:
            shutil.rmtree(os.path.dirname(pycode), ignore_errors=True)

    return _wrap([(g, *score_grid(g, S, m, results)) for g in grids], S, submission, structure, w)


def _wrap(rows, S, submission, structure, w, error=None):
    """rows: (grid, score, public entry, private entry) per grid."""
    by_role = {}
    for g, s, _, _ in rows:
        by_role.setdefault(g.role, []).append(s)
    ww = S["worst_weight"]                     # (1 - w) * mean + w * worst over the role's grids
    role_scores = {r: round(float((1 - ww) * np.mean(v) + ww * np.max(v)), 4) for r, v in by_role.items()}
    public = {"score": role_scores.get("selection"),
              "grids": {g.name: gp for g, _, gp, _ in rows if g.role == "selection"}, "submission_error": error}
    private = {"submission": os.path.abspath(submission), "role_scores": role_scores,
               "grids": {g.name: gq for g, _, _, gq in rows},
               "structure": structure, "submission_error": error,
               "wall_seconds": round(time.monotonic() - w, 1), "settings": S}
    return public, private


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("submission")
    ap.add_argument("--config", default=os.path.join(HERE, "config_min.json"))
    ap.add_argument("--out", default=None, help="directory for public.json / private.json")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    import logging
    import andes
    log_dir = os.path.join(a.out, "andes") if a.out else None
    if log_dir:                                # code generation's log; the workers write their own
        os.makedirs(log_dir, exist_ok=True)
        andes.config_logger(stream_level=40, log_path=log_dir, log_file="codegen.log", file_level=logging.INFO)
    else:
        andes.config_logger(stream_level=40, file=False)
    public, private = score_submission(a.submission, a.config, n_workers=a.workers, log_dir=log_dir)
    print(json.dumps(public, indent=1))
    print("role scores (private):", private["role_scores"], f"in {private['wall_seconds']} s")
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        for name, d in (("public", public), ("private", private)):
            with open(os.path.join(a.out, f"{name}.json"), "w") as f:
                json.dump(d, f, indent=1, default=float)


if __name__ == "__main__":
    main()
