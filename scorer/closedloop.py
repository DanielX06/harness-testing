"""Closed-loop scoring: put the submitted model into the grid in ANDES, in place of the device,
re-run each held-out disturbance and record the device's terminal P, Q, V, theta.

The submission is symbolic (see symbolic.py). It is turned into an ANDES model class by
filling a fixed template; the agent's content only enters as sympy-printed equation strings,
which ANDES parses with sympy. The class is registered at runtime and ANDES generates its
numerical code into a per-job copy of the pycode folder, so ~/.andes/pycode is never touched.
"""
import functools
import hashlib
import importlib
import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import types

import numpy as np
import sympy as sp

import symbolic

TEMPLATE = '''
from andes.core import (Algeb, ConstService, ExtAlgeb, ExtService, IdxParam, Model, ModelData,
                        NumParam, State)


class {cls}Data(ModelData):
    def __init__(self):
        ModelData.__init__(self)
        self.bus = IdxParam(model='ACNode', info='interface bus id', mandatory=True, status_parent=True)
        self.gen = IdxParam(model='StaticGen', info='static generator index', mandatory=True,
                            replaces=True)
        self.Sn = NumParam(default=100.0, info='device MVA base', unit='MVA', tex_name='S_n')
        self.gammap = NumParam(default=1.0, info='P ratio of linked static gen')
        self.gammaq = NumParam(default=1.0, info='Q ratio of linked static gen')
{params}


class {cls}({cls}Data, Model):
    """Submitted terminal model (generated)."""

    def __init__(self, system, config):
        {cls}Data.__init__(self)
        Model.__init__(self, system, config)
        self.flags.tds = True
        self.group = 'RenGen'
        self.a = ExtAlgeb(model='Bus', src='a', indexer=self.bus, tex_name=r'\\theta', e_str='-ue * Pe')
        self.v = ExtAlgeb(model='Bus', src='v', indexer=self.bus, tex_name='V', e_str='-ue * Qe')
        self.p0s = ExtService(model='StaticGen', src='p', indexer=self.gen, tex_name='P_{{0s}}')
        self.q0s = ExtService(model='StaticGen', src='q', indexer=self.gen, tex_name='Q_{{0s}}')
        self.kb = ConstService(v_str='sys_mva / Sn', tex_name='k_b')
        self.c_P0 = ConstService(v_str='gammap * p0s * kb', tex_name='P_0')
        self.c_Q0 = ConstService(v_str='gammaq * q0s * kb', tex_name='Q_0')
        self.c_V0 = ConstService(v_str='v', tex_name='V_0')
        self.c_theta0 = ConstService(v_str='a', tex_name=r'\\theta_0')
        self.c_Vset = ConstService(v_str='v', tex_name='V_{{set}}', info='voltage setpoint (Alter target)')
{states}
        self.Pd = Algeb(v_str={pinit!r}, e_str={pout!r}, tex_name='P_d', info='P, device base')
        self.Qd = Algeb(v_str={qinit!r}, e_str={qout!r}, tex_name='Q_d', info='Q, device base')
        self.Pe = Algeb(v_str='Pd / kb', e_str='Pd / kb - Pe', tex_name='P_e', info='P, system base')
        self.Qe = Algeb(v_str='Qd / kb', e_str='Qd / kb - Qe', tex_name='Q_e', info='Q, system base')
'''


def _andes_names(m):
    ren = {m.sym["V"]: sp.Symbol("v"), m.sym["theta"]: sp.Symbol("a"), m.sym["Vset"]: sp.Symbol("c_Vset")}
    ren.update({m.sym[k]: sp.Symbol(f"c_{k}") for k in symbolic.OPPOINT})
    ren.update({m.sym[k]: sp.Symbol(f"p_{k}") for k in m.params})
    ren.update({m.sym[k]: sp.Symbol(f"x_{k}") for k in m.state_names})
    return lambda ex: sp.sstr(ex.xreplace(ren), full_prec=True)


def class_source(m, cls):
    s = _andes_names(m)
    params = "\n".join(f"        self.p_{k} = NumParam(default={v!r}, info='submitted parameter {k}')"
                       for k, v in m.params.items()) or "        pass"
    states = "\n".join(f"        self.x_{k} = State(v_str={s(m.init[k])!r}, e_str={s(m.rhs[k])!r}, "
                       f"tex_name='x_{{{k}}}')" for k in m.state_names)
    # outputs initialise from the states' initial values, so a consistent init is exact
    return TEMPLATE.format(cls=cls, params=params, states=states,
                           pinit=s(m.out["P"]), pout=f"{s(m.out['P'])} - Pd",
                           qinit=s(m.out["Q"]), qout=f"{s(m.out['Q'])} - Qd")


def register(m, cls):
    """Create the ANDES model class and register it with ANDES's model list (in this process)."""
    import andes.models as am
    modname = cls.lower()
    full = f"andes.models.{modname}"
    if full not in sys.modules:
        mod = types.ModuleType(full)
        exec(compile(class_source(m, cls), f"<{full}>", "exec"), mod.__dict__)
        sys.modules[full] = mod
        setattr(am, modname, mod)
    if not any(f == modname for f, _ in am.file_classes):
        am.file_classes.append((modname, [cls]))
    return cls


def unregister(cls):
    import andes.models as am
    modname = cls.lower()
    am.file_classes[:] = [(f, c) for f, c in am.file_classes if f != modname]
    sys.modules.pop(f"andes.models.{modname}", None)
    if hasattr(am, modname):
        delattr(am, modname)


def _purge_pycode():
    """ANDES reuses an already-imported `pycode` package and only reloads its existing submodules,
    so a model generated after the first import (or a different job's folder) would be missed.
    Dropping it from sys.modules makes ANDES import the job's folder from scratch."""
    for k in [k for k in sys.modules if k == "pycode" or k.startswith("pycode.")]:
        del sys.modules[k]


def generate_code(pycode_path):
    """Generate numerical code for any registered model missing from `pycode_path`, in this
    process. (ANDES's own auto-generation uses a process pool that cannot see a model that was
    registered at runtime, and needs pathos.)"""
    import andes
    _purge_pycode()
    ss = andes.System(default_config=True, no_output=True, no_undill=True, pycode_path=pycode_path)
    ss.prepare(quick=True, incremental=True, nomp=True)
    _purge_pycode()


def class_name(spec_text):
    return "SUB" + hashlib.sha1(spec_text.encode()).hexdigest()[:10].upper()


def job_pycode():
    """Per-job copy of the generated-code folder so parallel jobs never share ~/.andes/pycode."""
    from andes.utils.paths import get_pycode_path
    base = get_pycode_path()
    if not os.path.exists(os.path.join(base, "__init__.py")):
        import andes
        andes.main.prepare(quick=True, nomp=True)
    d = tempfile.mkdtemp(prefix="pycode_")
    dst = os.path.join(d, "pycode")
    shutil.copytree(base, dst, ignore=shutil.ignore_patterns("SUB*", "__pycache__"))
    return dst


def run_tds(system_builder, run, device, dev_params, pycode_path, tf, tstep):
    """Build the grid with `device` in the slot, apply `run`'s disturbance, simulate.
    Returns dict(t, P, Q, V, theta) on a uniform grid, theta offset by its t=0 value."""
    w = time.monotonic()
    _purge_pycode()
    ss = system_builder(device, dev_params, run, pycode_path)
    ss.TDS.config.tf, ss.TDS.config.tstep, ss.TDS.config.no_tqdm = tf, tstep, 1
    ss.TDS.config.criteria = 0
    ss.TDS.run()
    if ss.TDS.busted or ss.exit_code != 0 or ss.dae.t < tf - 1e-9:
        raise RuntimeError(f"TDS failed at t={float(ss.dae.t):.4f} s (exit code {ss.exit_code})")
    m, ts = getattr(ss, device), ss.dae.ts
    bus = m.bus.v[0]
    ib = ss.Bus.idx.v.index(bus)
    raw_t = np.asarray(ts.t).ravel()
    Sb, Sn = ss.config.mva, m.Sn.v[0]
    P = np.asarray(ts.y[:, m.Pe.a]).ravel() * Sb / Sn
    Q = np.asarray(ts.y[:, m.Qe.a]).ravel() * Sb / Sn
    V = np.asarray(ts.y[:, ss.Bus.v.a[ib]]).ravel()
    a = np.asarray(ts.y[:, ss.Bus.a.a[ib]]).ravel()
    t = np.arange(0.0, tf + tstep / 2, tstep)
    out = {k: np.interp(t, raw_t, x) for k, x in (("P", P), ("Q", Q), ("V", V), ("theta", a - a[0]))}
    out["t"] = t
    out["seconds"] = time.monotonic() - w
    return out


# ---- parallel runs, one fresh process each (spawn: same behaviour on macOS and Linux) ---------
Y_BOUND = 50.0


def _worker(conn, spec_text, cls, pycode, builder, run, tf, tstep, grid_spec):
    try:
        import tqdm                            # ANDES's (disabled) bar would make an mp lock, leaked on terminate()
        tqdm.tqdm.set_lock(threading.RLock())
        import andes
        andes.config_logger(stream_level=50)
        m = symbolic.Model(json.loads(spec_text))
        register(m, cls)
        build = functools.partial(importlib.import_module(f"grids.{builder}").build, spec=json.loads(grid_spec))
        params = {f"p_{k}": v for k, v in m.params.items()}
        try:
            out = run_tds(build, run, cls, params, pycode, tf, tstep)
        except Exception as e:
            conn.send({"ok": False, "failure": "tds_failed", "detail": f"{type(e).__name__}: {e}"[-600:]})
            return
        arr = np.vstack([out[k] for k in ("P", "Q", "V", "theta")])
        if not np.all(np.isfinite(arr)):
            conn.send({"ok": False, "failure": "nan", "detail": "non-finite P, Q, V or theta"})
        elif np.max(np.abs(arr[:2])) > Y_BOUND:
            conn.send({"ok": False, "failure": "unstable", "detail": f"|P| or |Q| above {Y_BOUND} pu"})
        else:
            conn.send({"ok": True, "t": out["t"], "P": out["P"], "Q": out["Q"], "V": out["V"],
                       "theta": out["theta"], "seconds": out["seconds"]})
    except Exception:
        conn.send({"ok": False, "failure": "crash", "detail": traceback.format_exc()[-800:]})
    finally:
        conn.close()


def run_many(tasks, spec_text, cls, pycode, n_workers=None, timeout_s=900.0):
    """tasks: list of dict(id, builder, run, tf, tstep, grid_spec). Returns {id: result dict}."""
    ctx = mp.get_context("spawn")
    n_workers = n_workers or max(1, min(len(tasks), (os.cpu_count() or 2) - 1))
    pending, active, results = list(tasks), {}, {}
    while pending or active:
        while pending and len(active) < n_workers:
            t = pending.pop(0)
            parent, child = ctx.Pipe(duplex=False)
            p = ctx.Process(target=_worker, args=(child, spec_text, cls, pycode, t["builder"], t["run"],
                                                 t["tf"], t["tstep"], t["grid_spec"]), daemon=True)
            p.start()
            child.close()
            active[t["id"]] = (p, parent, time.monotonic())
        for tid, (p, conn, t0) in list(active.items()):
            if conn.poll():
                try:
                    results[tid] = conn.recv()
                except EOFError:
                    results[tid] = {"ok": False, "failure": "crash", "detail": "worker died"}
                p.join(5)
                conn.close()
                del active[tid]
            elif not p.is_alive():
                results[tid] = {"ok": False, "failure": "crash", "detail": f"worker exit code {p.exitcode}"}
                conn.close()
                del active[tid]
            elif time.monotonic() - t0 > timeout_s:
                p.terminate()
                p.join(5)
                conn.close()
                results[tid] = {"ok": False, "failure": "timeout", "detail": f"no result in {timeout_s:.0f} s"}
                del active[tid]
        time.sleep(0.05)
    return results
