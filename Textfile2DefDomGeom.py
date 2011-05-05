#!/usr/bin/env python
#
# Use doms.txt or nicknames.txt file to create a default-dom-geometry file and
# print the result to sys.stdout
#
# URL: http://icecube.wisc.edu/~testdaq/database_files/nicknames.txt

import optparse, sys
from DefaultDomGeometry import DefaultDomGeometryReader, DomsTxtReader, \
     NicknameReader

if __name__ == "__main__":
    p = optparse.OptionParser()

    p.add_option("-d", "--domstxt", type="string", dest="domsFile",
                 action="store", default=None,
                 help="DOM description file")
    p.add_option("-n", "--nicknames", type="string", dest="nicknames",
                 action="store", default=None,
                 help="DOM 'nicknames' file")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Be chatty")

    if opt.domsFile is not None and opt.nicknames is not None:
        raise SystemExit("Cannot specify both doms.txt and nicknames.txt files")

    if opt.nicknames is not None:
        newGeom = NicknameReader.parse(sys.argv[1])
    elif opt.domsFile is not None:
        newGeom = DomsTxtReader.parse(sys.argv[1])
    else:
        raise SystemExit("Please specify a doms.txt or nicknames.txt file")

    oldDomGeom = DefaultDomGeometryReader.parse()

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    newGeom.rewrite(False)
    oldDomGeom.rewrite()

    oldDomGeom.mergeMissing(newGeom)

    # dump the new default-dom-geometry data to sys.stdout
    oldDomGeom.dump()
