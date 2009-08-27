#!/usr/bin/env python
#
# Use nicknames.txt file to create a default-dom-geometry file and print the
# result to sys.stdout
#
# URL: http://icecube.wisc.edu/~testdaq/database_files/nicknames.txt

from DefaultDomGeometry import DefaultDomGeometryReader, NicknameReader

if __name__ == "__main__":
    # read in files
    nickGeom = NicknameReader().read()
    oldDomGeom = DefaultDomGeometryReader().read()

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    nickGeom.rewrite(False)
    oldDomGeom.rewrite()

    nickGeom.mergeMissing(oldDomGeom)

    # dump the new default-dom-geometry data to sys.stdout
    nickGeom.dump()
