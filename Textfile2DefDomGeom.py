#!/usr/bin/env python
#
# Use doms.txt or nicknames.txt file to create a default-dom-geometry file and
# print the result to sys.stdout
#
# URL: http://icecube.wisc.edu/~testdaq/database_files/nicknames.txt

import sys
from DefaultDomGeometry import DefaultDomGeometryReader, DomsTxtReader, \
     NicknameReader

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Please specify a file to load!")
    if len(sys.argv) > 2:
        raise SystemExit("Too many command-line arguments!")

    if sys.argv[1].endswith("nicknames.txt"):
        newGeom = NicknameReader.parse(sys.argv[1])
    elif sys.argv[1].endswith("doms.txt"):
        newGeom = DomsTxtReader.parse(sys.argv[1])
    else:
        raise SystemExit("File must be 'nicknames.txt' or 'doms.txt'," +
                         " not '%s'" % sys.argv[1])

    oldDomGeom = DefaultDomGeometryReader.parse()

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    newGeom.rewrite(False)
    oldDomGeom.rewrite()

    oldDomGeom.mergeMissing(newGeom)

    # dump the new default-dom-geometry data to sys.stdout
    oldDomGeom.dump()
