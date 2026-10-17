"""Parse and check a symbolic submission (submission.json). Pure data: nothing in it is executed.

Format (all expressions are strings in Python syntax):

{
  "params":  {"name": value, ...},
  "defs":    {"name": "expr", ...},          # optional intermediate quantities, in order, acyclic
  "states":  {"name": {"rhs": "expr", "init": "expr"}, ...},
  "outputs": {"P": "expr", "Q": "expr"}      # pu on the device rating
}

Symbols an expression may use:
  V, theta            terminal voltage magnitude (pu) and bus angle (rad), live
  Vset                the device's voltage setpoint (pu), live: equals V0 until the operator
                      steps it (staged voltage-reference tests)
  V0, theta0, P0, Q0  the operating point at t = 0 (P0, Q0 on the device rating)
  pi, params, states, defs (defs only after they are defined)
Init expressions may use V0, theta0, P0, Q0, pi, params and other states' inits (acyclic);
at t = 0, Vset = V0.
Functions: sin cos tan exp log sqrt tanh atan atan2 Abs Min Max.

Expressions are converted from the Python AST directly to sympy, node by node, against a
whitelist, so no string is ever eval'd. Anything outside the whitelist is rejected.
"""
import ast
import graphlib
import operator
import re

import numpy as np
import sympy as sp

FUNCS = {"sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt,
         "tanh": sp.tanh, "atan": sp.atan, "atan2": sp.atan2, "Abs": sp.Abs, "Min": sp.Min, "Max": sp.Max}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow}
INPUTS = ("V", "theta")
SETPOINTS = ("Vset",)               # live, set by the operator; Vset = V0 at t = 0
OPPOINT = ("V0", "theta0", "P0", "Q0")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
RESERVED = set(FUNCS) | set(INPUTS) | set(SETPOINTS) | set(OPPOINT) | {"pi", "t", "E", "I", "S", "N", "O", "Q", "P"}
MAX_STATES, MAX_DEFS, MAX_PARAMS, MAX_EXPR_CHARS = 60, 200, 200, 4000


class SubmissionError(Exception):
    pass


def _to_sympy(node, table, where):
    if isinstance(node, ast.Expression):
        return _to_sympy(node.body, table, where)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return sp.Float(node.value) if isinstance(node.value, float) else sp.Integer(node.value)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return sp.pi
        if node.id not in table:
            raise SubmissionError(f"{where}: unknown name '{node.id}'")
        return table[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _to_sympy(node.operand, table, where)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        if type(node.op) not in OPS:
            raise SubmissionError(f"{where}: operator {type(node.op).__name__} not allowed")
        return OPS[type(node.op)](_to_sympy(node.left, table, where), _to_sympy(node.right, table, where))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
            raise SubmissionError(f"{where}: only calls to {sorted(FUNCS)} are allowed")
        return FUNCS[node.func.id](*[_to_sympy(a, table, where) for a in node.args])
    raise SubmissionError(f"{where}: '{type(node).__name__}' not allowed in an expression")


def _parse(expr, table, where):
    if not isinstance(expr, str) or len(expr) > MAX_EXPR_CHARS:
        raise SubmissionError(f"{where}: expression must be a string under {MAX_EXPR_CHARS} chars")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise SubmissionError(f"{where}: syntax error: {e.msg}")
    return _to_sympy(tree, table, where)


def _check_name(n, kind):
    if not isinstance(n, str) or not NAME_RE.match(n) or n in RESERVED:
        raise SubmissionError(f"bad {kind} name '{n}' (letters, digits, _; not reserved: {sorted(RESERVED)})")


class Model:
    """Parsed submission. Symbols: inputs V, theta; op point V0, theta0, P0, Q0; params; states."""

    def __init__(self, spec):
        if not isinstance(spec, dict):
            raise SubmissionError("submission must be a JSON object")
        unknown = set(spec) - {"params", "defs", "states", "outputs", "notes"}
        if unknown:
            raise SubmissionError(f"unknown top-level keys {sorted(unknown)}")
        params = spec.get("params", {}) or {}
        defs = spec.get("defs", {}) or {}
        states = spec.get("states", {}) or {}
        outputs = spec.get("outputs")
        if not isinstance(outputs, dict) or set(outputs) != {"P", "Q"}:
            raise SubmissionError('"outputs" must have exactly the keys "P" and "Q"')
        if len(states) > MAX_STATES or len(defs) > MAX_DEFS or len(params) > MAX_PARAMS:
            raise SubmissionError(f"limits: {MAX_STATES} states, {MAX_DEFS} defs, {MAX_PARAMS} params")
        names = list(params) + list(defs) + list(states)
        if len(set(names)) != len(names):
            raise SubmissionError("a name is used twice across params, defs and states")
        for n in params:
            _check_name(n, "param")
            v = params[n]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
                raise SubmissionError(f"param {n} must be a finite number")
        for n in defs:
            _check_name(n, "def")
        for n, s in states.items():
            _check_name(n, "state")
            if not isinstance(s, dict) or set(s) != {"rhs", "init"}:
                raise SubmissionError(f'state {n} must be {{"rhs": ..., "init": ...}}')

        self.params = {n: float(v) for n, v in params.items()}
        self.state_names = list(states)
        self.sym = {n: sp.Symbol(n, real=True) for n in list(INPUTS) + list(SETPOINTS) + list(OPPOINT) + names}
        base = {n: self.sym[n] for n in list(INPUTS) + list(SETPOINTS) + list(OPPOINT) + list(params)
                + list(states)}

        # defs: parsed in order, each may use earlier defs; stored inlined (in terms of base symbols)
        self.defs = {}
        table = dict(base)
        for n, e in defs.items():
            ex = self._inline(_parse(e, table, f"def {n}"))
            self.defs[n] = ex
            table[n] = self.sym[n]
        full = dict(table)

        self.rhs = {n: self._inline(_parse(s["rhs"], full, f"state {n} rhs")) for n, s in states.items()}
        self.out = {k: self._inline(_parse(outputs[k], full, f"output {k}")) for k in ("P", "Q")}

        # inits: operating point, params and other states' inits only; resolved by substitution
        init_table = {n: self.sym[n] for n in list(OPPOINT) + list(params) + list(states)}
        raw = {n: _parse(s["init"], init_table, f"state {n} init") for n, s in states.items()}
        deps = {n: {d.name for d in ex.free_symbols if d.name in states} for n, ex in raw.items()}
        try:
            order = list(graphlib.TopologicalSorter(deps).static_order())
        except graphlib.CycleError as e:
            raise SubmissionError(f"state inits are circular: {e.args[1]}")
        self.init = {}
        for n in order:
            self.init[n] = raw[n].subs({self.sym[d]: self.init[d] for d in deps[n]})
        self._num = None

    def _inline(self, ex):
        # defs are already expressed in base symbols, one substitution pass is enough
        return ex.subs({self.sym[n]: d for n, d in self.defs.items()})

    # ---- numeric (array interface used by replay / linearize) -------------------------------
    def _compile(self):
        if self._num is None:
            X = [self.sym[n] for n in self.state_names]
            U = [self.sym["V"], self.sym["theta"], self.sym["Vset"]]
            OP = [self.sym[n] for n in OPPOINT]
            Pp = [self.sym[n] for n in self.params]
            f = sp.lambdify([X, U, OP, Pp], [self.rhs[n] for n in self.state_names] or [0], "numpy")
            g = sp.lambdify([X, U, OP, Pp], [self.out["P"], self.out["Q"]], "numpy")
            x0 = sp.lambdify([OP, Pp], [self.init[n] for n in self.state_names] or [0], "numpy")
            self._num = (f, g, x0, list(self.params.values()))
        return self._num

    def linearize(self, op):
        """Exact (symbolic) Jacobians at the model's own initial state for operating point op =
        (V0, theta0, P0, Q0), with V, theta held at V0, theta0 and Vset = V0. Returns x0, A, B, C, D, and
        the init residual max|dx/dt(x0)| (0 for an init that really is at rest)."""
        X = [self.sym[n] for n in self.state_names]
        U = [self.sym["V"], self.sym["theta"]]
        pt = {self.sym[k]: float(v) for k, v in zip(OPPOINT, op)}
        pt.update({self.sym[k]: v for k, v in self.params.items()})
        x0 = [float(self.init[n].subs(pt)) for n in self.state_names]
        pt.update(dict(zip(X, x0)))
        pt.update({U[0]: float(op[0]), U[1]: float(op[1]), self.sym["Vset"]: float(op[0])})
        F = sp.Matrix([self.rhs[n] for n in self.state_names]) if X else sp.zeros(0, 1)
        G = sp.Matrix([self.out["P"], self.out["Q"]])
        n = len(X)
        ev = lambda M, r, c: np.array(M.subs(pt).evalf(), dtype=float).reshape(r, c)
        A = ev(F.jacobian(X), n, n) if n else np.zeros((0, 0))
        B = ev(F.jacobian(U), n, 2) if n else np.zeros((0, 2))
        C = ev(G.jacobian(X), 2, n) if n else np.zeros((2, 0))
        D = ev(G.jacobian(U), 2, 2)
        f0 = ev(F, n, 1).ravel() if n else np.zeros(0)
        y0 = ev(G, 2, 1).ravel()
        return {"x0": np.array(x0), "A": A, "B": B, "C": C, "D": D,
                "init_residual": float(np.max(np.abs(f0))) if n else 0.0,
                "init_output_mismatch": float(np.max(np.abs(y0 - np.array(op[2:4], float))))}

    def bind(self, op, params=None):
        """Array model with the operating point fixed (op = V0, theta0, P0, Q0)."""
        return Bound(self, op, params)


class Bound:
    def __init__(self, model, op, params=None):
        self.m = model
        self.op = [float(v) for v in op]
        f, g, x0, p = model._compile()
        self.p = list(params) if params is not None else p
        self.f, self.g, self.x0f = f, g, x0
        self.n = len(model.state_names)

    def _u(self, u):
        """Inputs [V, theta] or [V, theta, Vset]; a missing setpoint is held at V0."""
        u = list(u)
        return u if len(u) == 3 else u[:2] + [self.op[0]]

    def init(self, u0, y0, meta=None):
        if self.n == 0:
            return np.zeros(0)
        return np.asarray(self.x0f(self.op, self.p), float).ravel()

    def rhs(self, t, x, u):
        if self.n == 0:
            return np.zeros(0)
        return np.asarray(self.f(list(x), self._u(u), self.op, self.p), float).ravel()

    def output(self, t, x, u):
        return np.asarray(self.g(list(x), self._u(u), self.op, self.p), float).ravel()


def load(path):
    import json
    with open(path) as fh:
        try:
            spec = json.load(fh)
        except json.JSONDecodeError as e:
            raise SubmissionError(f"not valid JSON: {e}")
    return Model(spec)
