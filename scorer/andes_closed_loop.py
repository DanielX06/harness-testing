"""Closed-loop simulation: the submitted model replaces the device in the grid in ANDES, each held-out
disturbance is re-run, and the device's terminal P, Q, V and theta are recorded.

ANDES only runs models written in its own format and registered in its model list. The submission is
turned into an ANDES model class by filling a fixed template; the submission's content only enters as
sympy-printed equation strings, which ANDES parses with sympy. The class is registered at runtime and
ANDES generates its numerical code into a private copy of the pycode folder, so ~/.andes/pycode is never
touched. Each simulation runs in a fresh process (spawn: the same behaviour on macOS and Linux) with a
time limit, several at once.
"""
import collections
import functools
import hashlib
import importlib
import json
import logging
import multiprocessing
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

from scorer import submission_parser

MODEL_CLASS_TEMPLATE = '''
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


# ---- the submission as an ANDES model class --------------------------------------------------------------
def andes_class_name(submission_text):
    """A class name unique to the submission's content."""
    return "SUB" + hashlib.sha1(submission_text.encode()).hexdigest()[:10].upper()


def _to_andes_names(model):
    """Expression printer that renames the submission's symbols to the template's ANDES variables:
    V -> v, theta -> a, Vset -> c_Vset, operating point -> c_*, params -> p_*, states -> x_*."""
    renames = {model.symbols["V"]: sp.Symbol("v"), model.symbols["theta"]: sp.Symbol("a"),
               model.symbols["Vset"]: sp.Symbol("c_Vset")}
    renames.update({model.symbols[name]: sp.Symbol(f"c_{name}") for name in submission_parser.OPERATING_POINT_NAMES})
    renames.update({model.symbols[name]: sp.Symbol(f"p_{name}") for name in model.params})
    renames.update({model.symbols[name]: sp.Symbol(f"x_{name}") for name in model.state_names})
    return lambda expression: sp.sstr(expression.xreplace(renames), full_prec=True)


def andes_class_source(model, class_name):
    """Python source of the ANDES model class for a parsed submission."""
    printed = _to_andes_names(model)
    params = "\n".join(f"        self.p_{name} = NumParam(default={value!r}, info='submitted parameter {name}')"
                       for name, value in model.params.items()) or "        pass"
    states = "\n".join(f"        self.x_{name} = State(v_str={printed(model.initial_values[name])!r}, "
                       f"e_str={printed(model.state_derivatives[name])!r}, tex_name='x_{{{name}}}')"
                       for name in model.state_names)
    # the outputs initialise from the states' initial values, so a consistent init is exact
    return MODEL_CLASS_TEMPLATE.format(cls=class_name, params=params, states=states,
                                       pinit=printed(model.outputs["P"]), pout=f"{printed(model.outputs['P'])} - Pd",
                                       qinit=printed(model.outputs["Q"]), qout=f"{printed(model.outputs['Q'])} - Qd")


def register_andes_class(model, class_name):
    """Create the ANDES model class and add it to ANDES's model list, in this process."""
    import andes.models as andes_models
    module_name = class_name.lower()
    full_name = f"andes.models.{module_name}"
    if full_name not in sys.modules:
        module = types.ModuleType(full_name)
        exec(compile(andes_class_source(model, class_name), f"<{full_name}>", "exec"), module.__dict__)
        sys.modules[full_name] = module
        setattr(andes_models, module_name, module)
    if not any(file_name == module_name for file_name, _ in andes_models.file_classes):
        andes_models.file_classes.append((module_name, [class_name]))
    return class_name


def unregister_andes_class(class_name):
    import andes.models as andes_models
    module_name = class_name.lower()
    andes_models.file_classes[:] = [(file_name, classes) for file_name, classes in andes_models.file_classes
                                    if file_name != module_name]
    sys.modules.pop(f"andes.models.{module_name}", None)
    if hasattr(andes_models, module_name):
        delattr(andes_models, module_name)


def _forget_imported_pycode():
    """ANDES reuses an already-imported `pycode` package and only reloads its existing submodules, so a model
    generated after the first import (or another job's folder) would be missed. Dropping it from
    sys.modules makes ANDES import the job's folder from scratch."""
    for name in [name for name in sys.modules if name == "pycode" or name.startswith("pycode.")]:
        del sys.modules[name]


def generate_numerical_code(pycode_path):
    """Generate numerical code for every registered model missing from pycode_path, in this process.
    (ANDES's own code generation uses a process pool that cannot see a model registered at runtime.)"""
    import andes
    _forget_imported_pycode()
    system = andes.System(default_config=True, no_output=True, no_undill=True, pycode_path=pycode_path)
    system.prepare(quick=True, incremental=True, nomp=True)
    _forget_imported_pycode()


def make_private_pycode_folder():
    """A copy of the generated-code folder for one scoring job, so parallel jobs never share ~/.andes/pycode."""
    from andes.utils.paths import get_pycode_path
    shared = get_pycode_path()
    if not os.path.exists(os.path.join(shared, "__init__.py")):
        import andes
        andes.main.prepare(quick=True, nomp=True)
    folder = tempfile.mkdtemp(prefix="pycode_")
    private = os.path.join(folder, "pycode")
    shutil.copytree(shared, private, ignore=shutil.ignore_patterns("SUB*", "__pycache__"))
    return private


# ---- one simulation ----------------------------------------------------------------------------------------
def _device_terminal_signals(system, device_class):
    """The device's terminal P, Q (on its own MVA base), bus V and angle at ANDES's own time steps."""
    device, series = getattr(system, device_class), system.dae.ts
    bus_position = system.Bus.idx.v.index(device.bus.v[0])
    times = np.asarray(series.t).ravel()
    system_base, device_base = system.config.mva, device.Sn.v[0]
    active_power = np.asarray(series.y[:, device.Pe.a]).ravel() * system_base / device_base
    reactive_power = np.asarray(series.y[:, device.Qe.a]).ravel() * system_base / device_base
    voltage = np.asarray(series.y[:, system.Bus.v.a[bus_position]]).ravel()
    angle = np.asarray(series.y[:, system.Bus.a.a[bus_position]]).ravel()
    return times, active_power, reactive_power, voltage, angle


def _save_partial_trajectory(system, device_class, path):
    """For a failed simulation: everything ANDES stored up to the failure, so the cause can be read off the
    trajectory (a runaway, a growing oscillation, a stiff state). Private; nothing in the loop reads it.
    Best effort: a problem here must never hide the simulation's own failure."""
    try:
        saved = {"err_msg": np.array(str(getattr(system.TDS, "err_msg", "") or "")),
                 "t_fail": np.array(float(system.dae.t)), "exit_code": np.array(int(system.exit_code))}
        try:
            saved.update(zip(("t", "P", "Q", "V", "theta"), _device_terminal_signals(system, device_class)))
        except Exception as error:
            saved["outputs_error"] = np.array(f"{type(error).__name__}: {error}")
        device, series = getattr(system, device_class), system.dae.ts
        for kind, values in (("x", "x"), ("y", "y")):
            variables = device.states if kind == "x" else device.algebs
            for name, variable in variables.items():      # the submission's own states and algebraics
                try:
                    saved[f"dev_{kind}_{name}"] = np.asarray(getattr(series, values)[:, variable.a]).ravel()
                except Exception:
                    pass
        np.savez_compressed(path, **saved)
    except Exception:
        pass


def run_closed_loop_simulation(build_system, run_name, device_class, device_params, pycode_path, end_time,
                               time_step, partial_trajectory_path=None):
    """Build the grid with device_class in the slot, apply the run's disturbance, simulate.
    Returns dict(t, P, Q, V, theta, seconds) on a uniform time grid, theta relative to its value at t = 0.
    On failure, saves what ANDES stored up to that point to partial_trajectory_path (.npz) if given."""
    started = time.monotonic()
    _forget_imported_pycode()
    system = build_system(device_class, device_params, run_name, pycode_path)
    system.TDS.config.tf, system.TDS.config.tstep, system.TDS.config.no_tqdm = end_time, time_step, 1
    system.TDS.config.criteria = 0
    system.TDS.run()
    if system.TDS.busted or system.exit_code != 0 or system.dae.t < end_time - 1e-9:
        if partial_trajectory_path:
            _save_partial_trajectory(system, device_class, partial_trajectory_path)
        raise RuntimeError(f"TDS failed at t={float(system.dae.t):.4f} s (exit code {system.exit_code})")
    raw_times, active_power, reactive_power, voltage, angle = _device_terminal_signals(system, device_class)
    times = np.arange(0.0, end_time + time_step / 2, time_step)
    result = {signal: np.interp(times, raw_times, values) for signal, values in
              (("P", active_power), ("Q", reactive_power), ("V", voltage), ("theta", angle - angle[0]))}
    result["t"] = times
    result["seconds"] = time.monotonic() - started
    return result


# ---- many simulations in parallel, one fresh process each ---------------------------------------------------
# |P| or |Q| above this (pu on the device rating) counts as the grid becoming unstable
SIGNAL_BOUND = 50.0
# ANDES logs go to files in the log folder (private, beside private.json; nothing in the loop reads them):
#   <task>.log            INFO and up, every task, small enough to commit
#   <task>.debug.log      the last DEBUG_TAIL_RECORDS DEBUG records, only for a task that failed (gitignored;
#                         a full DEBUG log is a line per 1 ms step, too big to keep for every run)
#   <task>_partial.npz    for a failed task: P, Q, V, theta and the submission's own states up to the
#                         failure (tds_failed), or the whole run (nan, unstable)
DEBUG_TAIL_RECORDS = 5000
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class _RecentRecords(logging.Handler):
    """Keeps the last n log records in memory; formats them only if they are written out."""

    def __init__(self, n):
        super().__init__(logging.DEBUG)
        self.records = collections.deque(maxlen=n)

    def emit(self, record):
        self.records.append(record)

    def write(self, path):
        with open(path, "w") as file:
            for record in self.records:
                try:
                    file.write(self.format(record) + "\n")
                except Exception:
                    pass


def _set_up_simulation_logs(andes, log_dir, task_id):
    """No terminal output and no file in ANDES's shared temp folder. With log_dir, a per-task INFO log and an
    in-memory DEBUG tail; returns the tail handler (None without log_dir)."""
    andes.config_logger(stream_level=50, file=False)
    if not log_dir:
        return None
    os.makedirs(log_dir, exist_ok=True)
    andes_logger = logging.getLogger("andes")
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(os.path.join(log_dir, f"{task_id}.log"), mode="w")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    andes_logger.addHandler(file_handler)
    recent = _RecentRecords(DEBUG_TAIL_RECORDS)
    recent.setFormatter(formatter)
    andes_logger.addHandler(recent)
    return recent


def _simulation_worker(connection, submission_text, class_name, pycode_path, builder_module, run_name, end_time,
                       time_step, case_spec_text, log_dir=None, task_id=None):
    """Runs in its own process: one closed-loop simulation, result sent back through the pipe."""
    recent_logs, result = None, None
    partial_path = os.path.join(log_dir, f"{task_id}_partial.npz") if log_dir else None
    try:
        import tqdm                                 # ANDES's (disabled) progress bar would make an mp lock, leaked on terminate()
        tqdm.tqdm.set_lock(threading.RLock())
        import andes
        try:
            recent_logs = _set_up_simulation_logs(andes, log_dir, task_id)
        except Exception:                           # logging must never cost a score
            andes.config_logger(stream_level=50, file=False)
            recent_logs, partial_path = None, None
        model = submission_parser.TerminalModel(json.loads(submission_text))
        register_andes_class(model, class_name)
        build_system = functools.partial(importlib.import_module(builder_module).build_system,
                                         case_spec=json.loads(case_spec_text))
        device_params = {f"p_{name}": value for name, value in model.params.items()}
        try:
            simulation = run_closed_loop_simulation(build_system, run_name, class_name, device_params, pycode_path,
                                                    end_time, time_step, partial_trajectory_path=partial_path)
        except Exception as error:
            result = {"ok": False, "failure": "tds_failed", "detail": f"{type(error).__name__}: {error}"[-600:]}
            return
        signals = np.vstack([simulation[name] for name in ("P", "Q", "V", "theta")])
        if not np.all(np.isfinite(signals)):
            result = {"ok": False, "failure": "nan", "detail": "non-finite P, Q, V or theta"}
        elif np.max(np.abs(signals[:2])) > SIGNAL_BOUND:
            result = {"ok": False, "failure": "unstable", "detail": f"|P| or |Q| above {SIGNAL_BOUND} pu"}
        else:
            result = {"ok": True, **{name: simulation[name] for name in ("t", "P", "Q", "V", "theta", "seconds")}}
        if not result["ok"] and partial_path:
            try:
                np.savez_compressed(partial_path, **{name: simulation[name] for name in ("t", "P", "Q", "V", "theta")})
            except Exception:
                pass
    except Exception:
        result = {"ok": False, "failure": "crash", "detail": traceback.format_exc()[-800:]}
    finally:
        if recent_logs is not None and result is not None and not result["ok"]:
            try:
                recent_logs.write(os.path.join(log_dir, f"{task_id}.debug.log"))
            except Exception:
                pass
        if result is not None:
            connection.send(result)
        connection.close()


class ParallelSimulator:
    """Runs closed-loop simulations, each in a fresh process, at most worker_count at a time, each stopped
    after time_limit_s seconds."""

    def __init__(self, worker_count=None, time_limit_s=900.0):
        self.worker_count = worker_count
        self.time_limit_s = time_limit_s

    def run(self, tasks, submission_text, class_name, pycode_path):
        """tasks: dicts with id, builder_module, run, end_time, time_step, case_spec_text and optionally log_dir.
        Returns {task id: result}; a result has ok True and the signals, or ok False with failure and detail."""
        context = multiprocessing.get_context("spawn")
        worker_count = self.worker_count or max(1, min(len(tasks), (os.cpu_count() or 2) - 1))
        waiting, running, results = list(tasks), {}, {}
        while waiting or running:
            while waiting and len(running) < worker_count:
                task = waiting.pop(0)
                receiving_end, sending_end = context.Pipe(duplex=False)
                process = context.Process(target=_simulation_worker, daemon=True, args=(
                    sending_end, submission_text, class_name, pycode_path, task["builder_module"], task["run"],
                    task["end_time"], task["time_step"], task["case_spec_text"], task.get("log_dir"), task["id"]))
                process.start()
                sending_end.close()
                running[task["id"]] = (process, receiving_end, time.monotonic())
            for task_id, (process, connection, started) in list(running.items()):
                if connection.poll():
                    try:
                        results[task_id] = connection.recv()
                    except EOFError:
                        results[task_id] = {"ok": False, "failure": "crash", "detail": "worker died"}
                    process.join(5)
                    connection.close()
                    del running[task_id]
                elif not process.is_alive():
                    results[task_id] = {"ok": False, "failure": "crash", "detail": f"worker exit code {process.exitcode}"}
                    connection.close()
                    del running[task_id]
                elif time.monotonic() - started > self.time_limit_s:
                    process.terminate()
                    process.join(5)
                    connection.close()
                    results[task_id] = {"ok": False, "failure": "timeout", "detail": f"no result in {self.time_limit_s:.0f} s"}
                    del running[task_id]
            time.sleep(0.05)
        return results
