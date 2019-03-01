#!/usr/bin/env python
"""
Import either the Python2 or Python3 function to reraise a system exception
"""

try:
    from reraise2 import reraise_excinfo
except SyntaxError:
    from reraise3 import reraise_excinfo
