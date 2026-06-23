"""Static AST analysis of toolkit tool methods to extract preconditions and effects.

Only WRITE tools are analyzed. Preconditions are extracted from top-level
If/Raise guard statements; effects are extracted via ast.walk over the full
function body.
"""

import ast
import inspect
import textwrap
from typing import Optional


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _parse_func(func) -> ast.FunctionDef:
    """Parse a method's source into an AST FunctionDef node."""
    source = inspect.getsource(func)
    source = textwrap.dedent(source)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            return node
    raise ValueError(f"No FunctionDef found in source of {func}")


def _body_is_just_raise(if_node: ast.If) -> bool:
    """True if the if-body is a single Raise statement."""
    return len(if_node.body) == 1 and isinstance(if_node.body[0], ast.Raise)


def _extract_self_db_attr(node: ast.expr) -> Optional[str]:
    """Extract <table> from a self.db.<table> attribute node."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
        and node.value.attr == "db"
    ):
        return node.attr
    return None


def _get_self_method_name(call: ast.Call) -> Optional[str]:
    """Return the method name from a self.<method>(...) call, or None."""
    if (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
    ):
        return call.func.attr
    return None


def _extract_literal_collection(node: ast.expr) -> Optional[list]:
    """Extract Python literal values from a Set/List/Tuple node."""
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        values = []
        for elt in node.elts:
            if not isinstance(elt, ast.Constant):
                return None
            values.append(elt.value)
        return values
    return None


# ---------------------------------------------------------------------------
# Step 1: Helper-to-table map
# ---------------------------------------------------------------------------

def build_helper_map(toolkit_cls) -> dict[str, dict]:
    """Scan _get_* methods on a toolkit class and build helper → {table, key_param}.

    Only captures direct DB lookups of the form:
        if key_param not in self.db.<table>: raise ValueError(...)
    Compound/delegating helpers (e.g. _get_payment_method) are skipped.
    """
    helper_map: dict[str, dict] = {}
    for name, method in inspect.getmembers(toolkit_cls, predicate=inspect.isfunction):
        if not name.startswith("_get_"):
            continue
        try:
            func_def = _parse_func(method)
        except (OSError, TypeError):
            continue
        params = [arg.arg for arg in func_def.args.args if arg.arg != "self"]
        if not params:
            continue
        key_param = params[0]
        table = _find_direct_db_table(func_def, key_param)
        if table is not None:
            helper_map[name] = {"table": table, "key_param": key_param}
    return helper_map


def _find_direct_db_table(func_def: ast.FunctionDef, key_param: str) -> Optional[str]:
    """Return the DB table name from `if key_param not in self.db.<table>: raise`."""
    for stmt in func_def.body:
        if not isinstance(stmt, ast.If) or not _body_is_just_raise(stmt):
            continue
        if not isinstance(stmt.test, ast.Compare):
            continue
        test = stmt.test
        if (
            len(test.ops) == 1
            and isinstance(test.ops[0], ast.NotIn)
            and isinstance(test.left, ast.Name)
            and test.left.id == key_param
            and len(test.comparators) == 1
        ):
            table = _extract_self_db_attr(test.comparators[0])
            if table is not None:
                return table
    return None


# ---------------------------------------------------------------------------
# Step 2: Variable provenance map (per-tool)
# ---------------------------------------------------------------------------

def _build_provenance_map(
    func_def: ast.FunctionDef,
    input_params: set[str],
    helper_map: dict[str, dict],
) -> dict[str, dict]:
    """Build local_var → {table, key_input} from `var = self._get_*(arg)` assignments.

    Only top-level Assign statements are scanned. key_input is the argument
    as passed (an input param name if it's a direct parameter, else the
    unparsed expression).
    """
    provenance: dict[str, dict] = {}
    for stmt in func_def.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            continue
        var_name = stmt.targets[0].id
        call = stmt.value
        if not isinstance(call, ast.Call):
            continue
        method_name = _get_self_method_name(call)
        if method_name is None or method_name not in helper_map:
            continue
        if not call.args:
            continue
        arg = call.args[0]
        if isinstance(arg, ast.Name) and arg.id in input_params:
            key_input = arg.id
        else:
            key_input = ast.unparse(arg)
        provenance[var_name] = {
            "table": helper_map[method_name]["table"],
            "key_input": key_input,
        }
    return provenance


# ---------------------------------------------------------------------------
# Step 3: Precondition extraction (top-level If/Raise guards only)
# ---------------------------------------------------------------------------

def _extract_preconditions(
    func_def: ast.FunctionDef,
    input_params: set[str],
    provenance: dict[str, dict],
) -> list[dict]:
    """Extract preconditions from top-level If/Raise guard statements."""
    preconditions = []
    for stmt in func_def.body:
        if not isinstance(stmt, ast.If) or not _body_is_just_raise(stmt):
            continue
        prec = _match_precondition(stmt.test, input_params, provenance)
        if prec is not None:
            preconditions.append(prec)
    return preconditions


def _match_precondition(
    test: ast.expr,
    input_params: set[str],
    provenance: dict[str, dict],
) -> Optional[dict]:
    return (
        _match_field_equals(test, provenance)
        or _match_input_in(test, input_params)
        or _match_opaque_predicate(test, provenance)
    )


def _match_field_equals(test: ast.expr, provenance: dict) -> Optional[dict]:
    """Match `var.field != literal` or `var.field == literal` guard.

    A `!=` guard means the precondition is field_equals (field must equal the
    value for the tool to proceed). A `==` guard means field_not_equals.
    """
    if not isinstance(test, ast.Compare):
        return None
    if len(test.ops) != 1 or len(test.comparators) != 1:
        return None
    op = test.ops[0]
    if not isinstance(op, (ast.NotEq, ast.Eq)):
        return None
    if not isinstance(test.left, ast.Attribute):
        return None
    if not isinstance(test.left.value, ast.Name):
        return None
    var_name = test.left.value.id
    if var_name not in provenance:
        return None
    comparator = test.comparators[0]
    if not isinstance(comparator, ast.Constant):
        return None
    kind = "field_equals" if isinstance(op, ast.NotEq) else "field_not_equals"
    return {
        "kind": kind,
        "table": provenance[var_name]["table"],
        "key_input": provenance[var_name]["key_input"],
        "field": test.left.attr,
        "value": comparator.value,
    }


def _match_input_in(test: ast.expr, input_params: set[str]) -> Optional[dict]:
    """Match `param not in {set/list/tuple}` guard."""
    if not isinstance(test, ast.Compare):
        return None
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.NotIn):
        return None
    if not isinstance(test.left, ast.Name) or test.left.id not in input_params:
        return None
    values = _extract_literal_collection(test.comparators[0])
    if values is None:
        return None
    return {"kind": "input_in", "param": test.left.id, "values": values}


def _match_opaque_predicate(test: ast.expr, provenance: dict) -> Optional[dict]:
    """Match `not self._is_*(var)` guard."""
    if not isinstance(test, ast.UnaryOp) or not isinstance(test.op, ast.Not):
        return None
    call = test.operand
    if not isinstance(call, ast.Call):
        return None
    method_name = _get_self_method_name(call)
    if method_name is None or not method_name.startswith("_is_"):
        return None
    result: dict = {"kind": "opaque_predicate", "predicate": method_name}
    if call.args and isinstance(call.args[0], ast.Name):
        var = call.args[0].id
        if var in provenance:
            result["table"] = provenance[var]["table"]
            result["key_input"] = provenance[var]["key_input"]
    return result


# ---------------------------------------------------------------------------
# Step 4: Effect extraction (ast.walk over full body)
# ---------------------------------------------------------------------------

def _extract_effects(
    func_def: ast.FunctionDef,
    provenance: dict[str, dict],
    input_params: set[str],
) -> list[dict]:
    """Extract state-mutation effects by walking the full function body."""
    effects: list[dict] = []
    seen: set[tuple] = set()

    def add(effect: dict) -> None:
        key = tuple(sorted((k, str(v)) for k, v in effect.items()))
        if key not in seen:
            seen.add(key)
            effects.append(effect)

    for node in ast.walk(func_def):
        if isinstance(node, ast.Assign):
            e = _match_field_set(node, provenance, input_params)
            if e:
                add(e)
            e = _match_record_create(node)
            if e:
                add(e)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            e = _match_list_append_entity(node.value, provenance)
            if e:
                add(e)
            e = _match_list_append_db(node.value)
            if e:
                add(e)

    return effects


def _match_field_set(
    node: ast.Assign,
    provenance: dict,
    input_params: set[str],
) -> Optional[dict]:
    """Match `var.field = value` where var is a tracked entity."""
    if len(node.targets) != 1:
        return None
    target = node.targets[0]
    if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
        return None
    var_name = target.value.id
    if var_name not in provenance:
        return None
    result: dict = {
        "kind": "field_set",
        "table": provenance[var_name]["table"],
        "key_input": provenance[var_name]["key_input"],
        "field": target.attr,
    }
    val = node.value
    if isinstance(val, ast.Constant):
        result["to"] = val.value
    elif isinstance(val, ast.Name) and val.id in input_params:
        result["from_input"] = val.id
    else:
        result["to"] = ast.unparse(val)
    return result


def _match_list_append_entity(call: ast.Call, provenance: dict) -> Optional[dict]:
    """Match `var.field.append/extend(...)` where var is a tracked entity."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in ("append", "extend"):
        return None
    inner = func.value
    if not isinstance(inner, ast.Attribute) or not isinstance(inner.value, ast.Name):
        return None
    var_name = inner.value.id
    if var_name not in provenance:
        return None
    return {
        "kind": "list_append",
        "table": provenance[var_name]["table"],
        "key_input": provenance[var_name]["key_input"],
        "field": inner.attr,
    }


def _match_record_create(node: ast.Assign) -> Optional[dict]:
    """Match `self.db.<table>[key] = obj`."""
    if len(node.targets) != 1:
        return None
    target = node.targets[0]
    if not isinstance(target, ast.Subscript):
        return None
    table = _extract_self_db_attr(target.value)
    if table is None:
        return None
    return {"kind": "record_create", "table": table}


def _match_list_append_db(call: ast.Call) -> Optional[dict]:
    """Match `self.db.<table>[key].<field>.append/extend(...)`."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in ("append", "extend"):
        return None
    inner = func.value
    if not isinstance(inner, ast.Attribute):
        return None
    field = inner.attr
    subscript = inner.value
    if not isinstance(subscript, ast.Subscript):
        return None
    table = _extract_self_db_attr(subscript.value)
    if table is None:
        return None
    return {"kind": "list_append_db", "table": table, "field": field}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_tool(
    func,
    input_params: set[str],
    helper_map: dict[str, dict],
) -> dict:
    """Return {preconditions, effects} for a single WRITE tool function.

    Args:
        func: The unbound function (getattr(type(toolkit), tool_name)).
        input_params: Set of input parameter names for the tool.
        helper_map: Output of build_helper_map for this toolkit class.
    """
    func_def = _parse_func(func)
    provenance = _build_provenance_map(func_def, input_params, helper_map)
    preconditions = _extract_preconditions(func_def, input_params, provenance)
    effects = _extract_effects(func_def, provenance, input_params)
    return {"preconditions": preconditions, "effects": effects}
