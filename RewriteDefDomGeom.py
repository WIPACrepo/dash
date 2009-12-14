#!/usr/bin/env python
#
# Rewrite the default-dom-geometry file from 64 DOMs per in-ice string to
# 60 DOMs per in-ice string and 32 DOMs per icetop hub and print the
# result to sys.stdout

import sys

from DefaultDomGeometry import DefaultDomGeometryReader

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        defDomGeom = DefaultDomGeometryReader.parse()
    else:
        defDomGeom = DefaultDomGeometryReader.parse(sys.argv[1])

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    defDomGeom.rewrite()

    # dump the new default-dom-geometry data to sys.stdout
    defDomGeom.dump()
