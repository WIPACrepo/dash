#!/usr/bin/env python
"""
IceCube helper methods
"""

import operator


# Import either the Python2 or Python3 function to reraise a system exception
try:
    from reraise2 import reraise_excinfo
except SyntaxError:
    from reraise3 import reraise_excinfo


class Comparable(object):
    """
    A class can extend/mixin this class and implement the compare_tuple()
    method containing all values to compare in their order of importance,
    and this class will automatically populate the special comparison and
    hash functions
    """
    def __eq__(self, other):
        if other is None:
            return False
        return self.compare_tuple == other.compare_tuple

    def __ge__(self, other):
        return not (self < other)

    def __gt__(self, other):
        if other is None:
            return False
        return self.compare_tuple > other.compare_tuple

    def __hash__(self):
        return hash(self.compare_tuple)

    def __le__(self, other):
        return not (self > other)

    def __lt__(self, other):
        if other is None:
            return True
        return self.compare_tuple < other.compare_tuple

    def __ne__(self, other):
        return not (self == other)

    @property
    def compare_tuple(self):
        raise NotImplementedError()
