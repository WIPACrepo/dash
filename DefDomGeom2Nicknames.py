#!/usr/bin/env python
#
# Use default-dom-geometry.xml to create a nicknames.txt file and print the
# result to sys.stdout

import sys

from DefaultDomGeometry import DefaultDomGeometryReader, NicknameReader

if __name__ == "__main__":
    # read in default-dom-geometry.xml
    #defDomGeom = DefaultDomGeometryReader.parse()

    if len(sys.argv) <= 1:
        defDomGeom = DefaultDomGeometryReader.parse()
    else:
        defDomGeom = DefaultDomGeometryReader.parse(sys.argv[1])

    NicknameReader.parse(geom=defDomGeom)

    # dump the new default-dom-geometry data to sys.stdout
    defDomGeom.dumpNicknames()
