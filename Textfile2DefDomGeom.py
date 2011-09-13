#!/usr/bin/env python
#
# Use doms.txt or nicknames.txt file to create a default-dom-geometry file and
# print the result to sys.stdout
#
# URL: http://icecube.wisc.edu/~testdaq/database_files/nicknames.txt
#
# The latest geometry file can be used to update the x/y/z coordinates
# for each DOM.  That information is linked to via the "Newest geometry"
# entry at http://wiki.icecube.wisc.edu/index.php/Geometry_releases
# and can be fetched with:
#
#    wget --user=icecube --ask-password <NEWEST_GEOMETRY_URL>

import optparse
import sys
from DefaultDomGeometry import DefaultDomGeometryReader, DomsTxtReader, \
     GeometryFileReader, NicknameReader

if __name__ == "__main__":
    p = optparse.OptionParser()

    p.add_option("-d", "--domstxt", type="string", dest="domsFile",
                 action="store", default=None,
                 help="DOM description file")
    p.add_option("-g", "--geometry", type="string", dest="geomFile",
                 action="store", default=None,
                 help="IceCube geometry settings")
    p.add_option("-m", "--min-coord-diff", type="float", dest="minCoordDiff",
                 action="store", default=0.00001,
                 help="Minimum difference before a coordinate is changed")
    p.add_option("-n", "--nicknames", type="string", dest="nicknames",
                 action="store", default=None,
                 help="DOM 'nicknames' file")
    p.add_option("-o", "--olddefdomgeom", type="string", dest="oldDefDomGeom",
                 action="store", default=None,
                 help="Previous default-dom-geometry file")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Be chatty")

    opt, args = p.parse_args()

    if opt.domsFile is not None and \
            opt.nicknames is not None:
        raise SystemExit(
            "Cannot specify both doms.txt and nicknames.txt files")

    if opt.nicknames is not None:
        newGeom = NicknameReader.parse(opt.nicknames)
    elif opt.domsFile is not None:
        newGeom = DomsTxtReader.parse(opt.domsFile)
    elif opt.geomFile is not None:
        newGeom = None
    else:
        raise SystemExit("Please specify a doms.txt, nicknames.txt" +
                         " or geometry file")

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    if newGeom is not None:
        newGeom.rewrite(False)

    # load in the existing default-dom-geometry file
    if opt.oldDefDomGeom is None:
        oldDomGeom = DefaultDomGeometryReader.parse()
    else:
        oldDomGeom = DefaultDomGeometryReader.parse(opt.oldDefDomGeom)

    # update geometry info in existing file
    if opt.geomFile is not None:
        GeometryFileReader.parse(opt.geomFile, defDomGeom=oldDomGeom,
                                 minCoordDiff=opt.minCoordDiff)

    # copy new info to existing file
    if newGeom is not None:
        oldDomGeom.update(newGeom, opt.verbose)

    # dump the new default-dom-geometry data to sys.stdout
    oldDomGeom.dump()
