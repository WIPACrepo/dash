#!/usr/bin/env python
#
# Use default-dom-geometry.xml to create a nicknames.txt file and print the
# result to sys.stdout

import sys

from DefaultDomGeometry import DefaultDomGeometryReader, NicknameReader

if __name__ == "__main__":
    # read in default-dom-geometry.xml
    #defDomGeom = DefaultDomGeometryReader().read()

    if len(sys.argv) <= 1:
        defDomGeom = DefaultDomGeometryReader().read()
    else:
        defDomGeom = DefaultDomGeometryReader().read(sys.argv[1])

    NicknameReader().read(geom=defDomGeom)

    # dump the new default-dom-geometry data to sys.stdout
    defDomGeom.dumpNicknames()
