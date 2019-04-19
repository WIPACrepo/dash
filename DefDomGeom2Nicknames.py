#!/usr/bin/env python
"""
Use default-dom-geometry.xml to create a nicknames.txt file and print the
result to sys.stdout
"""

import sys

from DefaultDomGeometry import DefaultDomGeometryReader, NicknameReader

def main():
    "Main program"
    # read in default-dom-geometry.xml
    if len(sys.argv) <= 1:
        geom = DefaultDomGeometryReader.parse()
    else:
        geom = DefaultDomGeometryReader.parse(fileName=sys.argv[1])

    NicknameReader.parse(defDomGeom=geom)

    # dump the new default-dom-geometry data to sys.stdout
    geom.dumpNicknames()

if __name__ == "__main__":
    main()
