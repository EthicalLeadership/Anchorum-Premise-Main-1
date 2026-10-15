"""probe_celpy.py verify the installed celpy supports the API we depend on.

Exit 0 = all checks passed. Any FAIL prints a specific message and exits
non-zero. Run once per environment before deploying a PolicyRuntime change.

This probe asserts the current public API shape; update when celpy's API changes.
"""
import sys

try:
    import celpy
    from celpy import celtypes
except ImportError as exc:
    sys.exit(f"FAIL celpy not installed: {exc}")

print(f"celpy version: {getattr(celpy, '__version__', 'unknown')}")

# Check 1: custom function registration via program(functions=...).
# cel-python 0.5.0 has no Environment.add_function; functions are bound at
# program-construction time via a Dict[str, Callable], and the environment
# declares them via annotations=.

def _probe_parse_ts(value: celtypes.StringType) -> celtypes.IntType:
    return celtypes.IntType(0)

try:
    env = celpy.Environment(annotations={"parse_ts": celtypes.FunctionType})
    ast = env.compile("parse_ts('x') == 0")
    prgm = env.program(ast, functions={"parse_ts": _probe_parse_ts})
    result = prgm.evaluate({})
    print(f"OK   program(functions=...) -> {result!r}")
except Exception as exc:
    sys.exit(f"FAIL program(functions=...): {exc}")

# Check 2: compile + evaluate + custom function via functions= binding.
try:
    ast = env.compile("parse_ts('2024-01-01') == 0")
    p = env.program(ast, functions={"parse_ts": _probe_parse_ts})
    result = p.evaluate({})
    print(f"OK   compile + evaluate + custom fn (type={type(result).__name__}, value={result!r})")
except Exception as exc:
    sys.exit(f"FAIL compile/evaluate: {exc}")

# Check 3: comments inside compiled expressions.
try:
    p = env.program(env.compile("// comment\n1 == 1"))
    result = p.evaluate({})
    print(f"OK   inline comments (type={type(result).__name__}, value={result!r})")
except Exception as exc:
    sys.exit(f"FAIL comments: {exc}")

# Check 4: exception class for missing map key. Informational.
try:
    env.program(env.compile("fields.x")).evaluate(
        {"fields": celtypes.MapType({})}
    )
    print("WARN missing-key access did NOT raise (unexpected)")
except Exception as exc:
    name = type(exc).__name__
    if name == "CELEvalError":
        print(f"OK   exception class is CELEvalError")
    else:
        print(f"WARN exception class is {name!r}, not CELEvalError "
              f"(PolicyRuntime catches all exceptions, so no action needed, "
              f"but note the divergence)")


# Check 5: map expression return type. Informational PolicyRuntime must
# know whether decisions come back as dict or celtypes.MapType.
try:
    p = env.program(env.compile('{"route": "TEST", "severity": "info"}'))
    result = p.evaluate({})
    print(f"INFO map expression -> {type(result).__name__}, "
          f"isinstance dict={isinstance(result, dict)}")
except Exception as exc:
    print(f"WARN map expression failed: {type(exc).__name__}: {exc}")

print("probe complete")
