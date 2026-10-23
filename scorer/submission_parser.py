"""Parse and check a submission (submission.json): the solver's terminal model, written as equations.

Nothing in a submission is ever executed. Each expression string is parsed with Python's own parser
(ast) and converted node by node into a sympy expression, against a whitelist of names, operators and
functions, so no string is ever eval'd. Anything outside the whitelist is rejected with a
SubmissionError, and so is anything else that goes wrong while parsing: the scorer scores a rejected
submission 2 and never crashes on one.

The scorer and the solver's checker use this same file (the solver gets a copy as
tools/submission_parser.py), so a submission the checker accepts is one the scorer can parse.

Format (every expression is a string in Python syntax):

{
  "params":  {"name": value, ...},
  "defs":    {"name": "expr", ...},          # optional intermediate quantities, in order, acyclic
  "states":  {"name": {"rhs": "expr", "init": "expr"}, ...},
  "outputs": {"P": "expr", "Q": "expr"},     # pu on the device rating
  "notes":   "optional free text"
}

Symbols an expression may use:
  V, theta            terminal voltage magnitude (pu) and bus angle (rad), live
  Vset                the device's voltage setpoint (pu), live: equals V0 until the operator
                      steps it (staged voltage-reference tests)
  V0, theta0, P0, Q0  the operating point at t = 0 (P0, Q0 on the device rating)
  pi, params, states, defs (a def only after it is defined)
Init expressions may use V0, theta0, P0, Q0, pi, params and other states' inits (acyclic);
at t = 0, Vset = V0.
Functions: sin cos tan exp log sqrt tanh atan atan2 Abs Min Max.
"""
import ast
import graphlib
import json
import math
import operator
import re

import numpy as np
import sympy as sp

# name -> (sympy function, fewest arguments, most arguments or None for no limit)
ALLOWED_FUNCTIONS = {
    "sin": (sp.sin, 1, 1), "cos": (sp.cos, 1, 1), "tan": (sp.tan, 1, 1), "exp": (sp.exp, 1, 1),
    "log": (sp.log, 1, 2), "sqrt": (sp.sqrt, 1, 1), "tanh": (sp.tanh, 1, 1), "atan": (sp.atan, 1, 1),
    "atan2": (sp.atan2, 2, 2), "Abs": (sp.Abs, 1, 1), "Min": (sp.Min, 1, None), "Max": (sp.Max, 1, None),
}
ALLOWED_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                     ast.Div: operator.truediv, ast.Pow: operator.pow}

INPUT_NAMES = ("V", "theta")
SETPOINT_NAMES = ("Vset",)                      # live, set by the operator; Vset = V0 at t = 0
OPERATING_POINT_NAMES = ("V0", "theta0", "P0", "Q0")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
# sympy's one-letter constants (E, I, S, N, O, Q, P) are reserved so a name can never shadow one
RESERVED_NAMES = (set(ALLOWED_FUNCTIONS) | set(INPUT_NAMES) | set(SETPOINT_NAMES) | set(OPERATING_POINT_NAMES)
                  | {"pi", "t", "E", "I", "S", "N", "O", "Q", "P"})

MAX_STATES, MAX_DEFS, MAX_PARAMS, MAX_EXPRESSION_CHARS = 60, 200, 200, 4000
# Defs are substituted into whatever uses them. A def used twice by the next one doubles in size at every
# step, so a short chain of defs can describe an expression too large to parse, build or simulate. Each
# expression is measured before it is written out. The largest in the 30 submissions so far (the true
# device's included) has 262 nodes; at the limit, parsing alone takes about a second.
MAX_EXPANDED_NODES = 20_000
# sympy evaluates a power of two numbers exactly, so 10**10**10 would never finish
MAX_NUMBER_EXPONENT = 1000


class SubmissionError(Exception):
    """The submission breaks a rule. The message says which rule and where."""


# ---- expressions -------------------------------------------------------------------------------------
def parse_expression(text, visible_symbols, where):
    """One expression string -> sympy, using only the symbols in visible_symbols (name -> sympy Symbol)."""
    if not isinstance(text, str) or len(text) > MAX_EXPRESSION_CHARS:
        raise SubmissionError(f"{where}: expression must be a string under {MAX_EXPRESSION_CHARS} chars")
    if "\x00" in text:                 # Python 3.12 and later call this a SyntaxError, earlier versions a ValueError
        raise SubmissionError(f"{where}: expression contains a null byte")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as error:
        raise SubmissionError(f"{where}: syntax error: {error.msg}")
    return _sympy_from_ast(tree, visible_symbols, where)


def _sympy_from_ast(node, visible_symbols, where):
    if isinstance(node, ast.Expression):
        return _sympy_from_ast(node.body, visible_symbols, where)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return sp.Float(node.value) if isinstance(node.value, float) else sp.Integer(node.value)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return sp.pi
        if node.id not in visible_symbols:
            raise SubmissionError(f"{where}: unknown name '{node.id}'")
        return visible_symbols[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = _sympy_from_ast(node.operand, visible_symbols, where)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        return _binary_chain(node, visible_symbols, where)
    if isinstance(node, ast.Call):
        return _function_call(node, visible_symbols, where)
    raise SubmissionError(f"{where}: '{type(node).__name__}' not allowed in an expression")


def _binary_chain(node, visible_symbols, where):
    """a + b - c * d ...: Python parses a long sum as a chain that leans left. Walking down the chain in a
    loop, rather than recursing into it, lets a sum of thousands of terms parse without reaching Python's
    recursion limit. The operations are applied in the same order as a recursive walk would apply them."""
    chain = []
    while isinstance(node, ast.BinOp):
        if type(node.op) not in ALLOWED_OPERATORS:
            raise SubmissionError(f"{where}: operator {type(node.op).__name__} not allowed")
        chain.append(node)
        node = node.left
    value = _sympy_from_ast(node, visible_symbols, where)
    for binary in reversed(chain):
        right = _sympy_from_ast(binary.right, visible_symbols, where)
        if isinstance(binary.op, ast.Pow) and right.is_Number and abs(right) > MAX_NUMBER_EXPONENT:
            raise SubmissionError(f"{where}: exponent {right} is larger than {MAX_NUMBER_EXPONENT}")
        value = ALLOWED_OPERATORS[type(binary.op)](value, right)
    return value


def _function_call(node, visible_symbols, where):
    name = node.func.id if isinstance(node.func, ast.Name) else None
    if name not in ALLOWED_FUNCTIONS or node.keywords:
        raise SubmissionError(f"{where}: only calls to {sorted(ALLOWED_FUNCTIONS)} are allowed")
    function, fewest, most = ALLOWED_FUNCTIONS[name]
    count = len(node.args)
    if count < fewest or (most is not None and count > most):
        allowed = str(fewest) if fewest == most else (f"at least {fewest}" if most is None else f"{fewest} or {most}")
        plural = "" if allowed in ("1", "at least 1") else "s"
        raise SubmissionError(f"{where}: {name} takes {allowed} argument{plural}, got {count}")
    return function(*[_sympy_from_ast(argument, visible_symbols, where) for argument in node.args])


def expanded_size(expression, sizes_of_named_parts):
    """Nodes in the expression once every named part in it (a def, or another state's init) is written out
    in full. A named part's symbol counts as that part's own expanded size, so nothing is written out."""
    def count(node):
        if isinstance(node, sp.Symbol) and node.name in sizes_of_named_parts:
            return sizes_of_named_parts[node.name]
        return 1 + sum(count(argument) for argument in node.args)
    return count(expression)


def _check_size(size, where, substituted="its defs"):
    if size > MAX_EXPANDED_NODES:
        raise SubmissionError(f"{where} has about {size:.3g} nodes once {substituted} are substituted in "
                              f"(limit {MAX_EXPANDED_NODES}); simplify the model or nest fewer {substituted.split()[-1]}")


def _check_name(name, kind):
    if not isinstance(name, str) or not NAME_PATTERN.match(name) or name in RESERVED_NAMES:
        raise SubmissionError(f"bad {kind} name '{name}' (letters, digits, _; not reserved: {sorted(RESERVED_NAMES)})")


def _is_finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


# ---- the model ---------------------------------------------------------------------------------------
class TerminalModel:
    """A parsed submission.

    Every expression is sympy, written in terms of the base symbols (the inputs V and theta, the setpoint
    Vset, the operating point, the params and the states) with every def substituted in.
        params             name -> value
        state_names        in submission order
        defs               name -> expression
        state_derivatives  name -> d(state)/dt (the submission's "rhs")
        outputs            "P" and "Q" -> expression
        initial_values     name -> expression in the operating point and params only
        symbols            name -> sympy Symbol, for every name above
    """

    def __init__(self, submission):
        try:
            self._parse(submission)
        except SubmissionError:
            raise
        except RecursionError:
            raise SubmissionError("an expression is nested too deeply to parse")
        except Exception as error:              # anything else a strange submission can provoke inside sympy
            raise SubmissionError(f"could not parse the submission ({type(error).__name__}: {error})")
        self._numeric = None

    def _parse(self, submission):
        if not isinstance(submission, dict):
            raise SubmissionError("submission must be a JSON object")
        unknown_keys = set(submission) - {"params", "defs", "states", "outputs", "notes"}
        if unknown_keys:
            raise SubmissionError(f"unknown top-level keys {sorted(unknown_keys)}")
        params = submission.get("params", {}) or {}
        defs = submission.get("defs", {}) or {}
        states = submission.get("states", {}) or {}
        outputs = submission.get("outputs")
        for key, value in (("params", params), ("defs", defs), ("states", states)):
            if not isinstance(value, dict):
                raise SubmissionError(f'"{key}" must be a JSON object')
        if not isinstance(outputs, dict) or set(outputs) != {"P", "Q"}:
            raise SubmissionError('"outputs" must have exactly the keys "P" and "Q"')
        if len(states) > MAX_STATES or len(defs) > MAX_DEFS or len(params) > MAX_PARAMS:
            raise SubmissionError(f"limits: {MAX_STATES} states, {MAX_DEFS} defs, {MAX_PARAMS} params")
        names = list(params) + list(defs) + list(states)
        if len(set(names)) != len(names):
            raise SubmissionError("a name is used twice across params, defs and states")
        for name in params:
            _check_name(name, "param")
            if not _is_finite_number(params[name]):
                raise SubmissionError(f"param {name} must be a finite number")
        for name in defs:
            _check_name(name, "def")
        for name, state in states.items():
            _check_name(name, "state")
            if not isinstance(state, dict) or set(state) != {"rhs", "init"}:
                raise SubmissionError(f'state {name} must be {{"rhs": ..., "init": ...}}')

        self.params = {name: float(value) for name, value in params.items()}
        self.state_names = list(states)
        fixed_names = list(INPUT_NAMES) + list(SETPOINT_NAMES) + list(OPERATING_POINT_NAMES)
        self.symbols = {name: sp.Symbol(name, real=True) for name in fixed_names + names}

        # defs are parsed in order, each seeing the ones before it, and stored with those substituted in
        visible = {name: self.symbols[name] for name in fixed_names + list(params) + list(states)}
        self.defs, def_sizes = {}, {}
        for name, text in defs.items():
            raw = parse_expression(text, visible, f"def {name}")
            def_sizes[name] = expanded_size(raw, def_sizes)
            _check_size(def_sizes[name], f"def {name}")
            self.defs[name] = self._substitute_defs(raw)
            visible[name] = self.symbols[name]

        self.state_derivatives = {}
        for name, state in states.items():
            raw = parse_expression(state["rhs"], visible, f"state {name} rhs")
            _check_size(expanded_size(raw, def_sizes), f"state {name} rhs")
            self.state_derivatives[name] = self._substitute_defs(raw)
        self.outputs = {}
        for key in ("P", "Q"):
            raw = parse_expression(outputs[key], visible, f"output {key}")
            _check_size(expanded_size(raw, def_sizes), f"output {key}")
            self.outputs[key] = self._substitute_defs(raw)

        # inits: operating point, params and other states' inits only, resolved in dependency order
        init_visible = {name: self.symbols[name] for name in list(OPERATING_POINT_NAMES) + list(params) + list(states)}
        raw_inits = {name: parse_expression(state["init"], init_visible, f"state {name} init")
                     for name, state in states.items()}
        depends_on = {name: {symbol.name for symbol in expression.free_symbols if symbol.name in states}
                      for name, expression in raw_inits.items()}
        try:
            order = list(graphlib.TopologicalSorter(depends_on).static_order())
        except graphlib.CycleError as error:
            raise SubmissionError(f"state inits are circular: {error.args[1]}")
        self.initial_values, init_sizes = {}, {}
        for name in order:
            init_sizes[name] = expanded_size(raw_inits[name], init_sizes)
            _check_size(init_sizes[name], f"state {name} init", substituted="the other states' inits")
            self.initial_values[name] = raw_inits[name].subs(
                {self.symbols[other]: self.initial_values[other] for other in depends_on[name]})

    def _substitute_defs(self, expression):
        # every stored def is already written in base symbols, so one substitution pass is enough
        return expression.subs({self.symbols[name]: definition for name, definition in self.defs.items()})

    # ---- linearization (scorer and checker) ----------------------------------------------------------
    def linearize(self, operating_point):
        """Exact (symbolic) Jacobians at the model's own initial state for the operating point
        (V0, theta0, P0, Q0), with V and theta held at V0 and theta0 and Vset = V0.

        Returns x0 (the initial state), A, B, C, D (inputs V, theta; outputs P, Q), init_residual
        (max |dx/dt| at x0, 0 for an init that really is at rest) and init_output_mismatch
        (max |output - (P0, Q0)| at x0)."""
        states = [self.symbols[name] for name in self.state_names]
        inputs = [self.symbols["V"], self.symbols["theta"]]
        point = {self.symbols[name]: float(value) for name, value in zip(OPERATING_POINT_NAMES, operating_point)}
        point.update({self.symbols[name]: value for name, value in self.params.items()})
        x0 = [float(self.initial_values[name].subs(point)) for name in self.state_names]
        point.update(dict(zip(states, x0)))
        point.update({inputs[0]: float(operating_point[0]), inputs[1]: float(operating_point[1]),
                      self.symbols["Vset"]: float(operating_point[0])})
        derivatives = (sp.Matrix([self.state_derivatives[name] for name in self.state_names]) if states
                       else sp.zeros(0, 1))
        outputs = sp.Matrix([self.outputs["P"], self.outputs["Q"]])
        n = len(states)

        def evaluate(matrix, rows, columns):
            return np.array(matrix.subs(point).evalf(), dtype=float).reshape(rows, columns)

        A = evaluate(derivatives.jacobian(states), n, n) if n else np.zeros((0, 0))
        B = evaluate(derivatives.jacobian(inputs), n, 2) if n else np.zeros((0, 2))
        C = evaluate(outputs.jacobian(states), 2, n) if n else np.zeros((2, 0))
        D = evaluate(outputs.jacobian(inputs), 2, 2)
        rates_at_start = evaluate(derivatives, n, 1).ravel() if n else np.zeros(0)
        outputs_at_start = evaluate(outputs, 2, 1).ravel()
        return {"x0": np.array(x0), "A": A, "B": B, "C": C, "D": D,
                "init_residual": float(np.max(np.abs(rates_at_start))) if n else 0.0,
                "init_output_mismatch": float(np.max(np.abs(outputs_at_start - np.array(operating_point[2:4], float))))}

    # ---- numeric version (the checker's open-loop replay) --------------------------------------------
    def bind(self, operating_point, params=None):
        """The model as numpy functions with the operating point (V0, theta0, P0, Q0) fixed."""
        return BoundTerminalModel(self, operating_point, params)

    def numeric_functions(self):
        """(state derivative, outputs, initial state, param values) as numpy functions; built once."""
        if self._numeric is None:
            states = [self.symbols[name] for name in self.state_names]
            inputs = [self.symbols["V"], self.symbols["theta"], self.symbols["Vset"]]
            point = [self.symbols[name] for name in OPERATING_POINT_NAMES]
            params = [self.symbols[name] for name in self.params]
            derivative = sp.lambdify([states, inputs, point, params],
                                     [self.state_derivatives[name] for name in self.state_names] or [0], "numpy")
            outputs = sp.lambdify([states, inputs, point, params], [self.outputs["P"], self.outputs["Q"]], "numpy")
            initial_state = sp.lambdify([point, params],
                                        [self.initial_values[name] for name in self.state_names] or [0], "numpy")
            self._numeric = (derivative, outputs, initial_state, list(self.params.values()))
        return self._numeric


class BoundTerminalModel:
    """A TerminalModel as numpy functions, with the operating point fixed.
    Inputs are [V, theta] or [V, theta, Vset]; a missing setpoint is held at V0."""

    def __init__(self, model, operating_point, params=None):
        self.model = model
        self.operating_point = [float(value) for value in operating_point]
        self._derivative, self._outputs, self._initial_state, default_params = model.numeric_functions()
        self.param_values = list(params) if params is not None else default_params
        self.state_count = len(model.state_names)

    def _with_setpoint(self, inputs):
        inputs = list(inputs)
        return inputs if len(inputs) == 3 else inputs[:2] + [self.operating_point[0]]

    def initial_state(self):
        if self.state_count == 0:
            return np.zeros(0)
        return np.asarray(self._initial_state(self.operating_point, self.param_values), float).ravel()

    def state_derivative(self, time, state, inputs):
        if self.state_count == 0:
            return np.zeros(0)
        return np.asarray(self._derivative(list(state), self._with_setpoint(inputs), self.operating_point,
                                           self.param_values), float).ravel()

    def outputs(self, time, state, inputs):
        return np.asarray(self._outputs(list(state), self._with_setpoint(inputs), self.operating_point,
                                        self.param_values), float).ravel()


def load_submission(path):
    """Read and parse submission.json; any problem with the file is a SubmissionError."""
    try:
        with open(path, encoding="utf-8") as file:
            submission = json.load(file)
    except json.JSONDecodeError as error:
        raise SubmissionError(f"not valid JSON: {error}")
    except UnicodeDecodeError as error:
        raise SubmissionError(f"not a text file: {error}")
    return TerminalModel(submission)
