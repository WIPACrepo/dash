try:
    eval("1 if True else 0")
except SyntaxError:
    raise ImportError("Requires python >= 2.5 ( ternary operator support )")
