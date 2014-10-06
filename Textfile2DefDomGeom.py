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

if __name__ == "__main__":
    import argparse

    from DefaultDomGeometry import DefaultDomGeometryReader, DomsTxtReader, \
        GeometryFileReader, NicknameReader

    p = argparse.ArgumentParser()

    p.add_argument("-d", "--domstxt", dest="domsFile",
                 help="DOM description file")
    p.add_argument("-g", "--geometry", dest="geomFile",
                 help="IceCube geometry settings")
    p.add_argument("-m", "--min-coord-diff", type=float, dest="minCoordDiff",
                 default=0.00001,
                 help="Minimum difference before a coordinate is changed")
    p.add_argument("-n", "--nicknames", dest="nicknames",
                 help="DOM 'nicknames' file")
    p.add_argument("-o", "--olddefdomgeom", dest="oldDefDomGeom",
                 help="Previous default-dom-geometry file")
    p.add_argument("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Be chatty")

    args = p.parse_args()

    if args.domsFile is not None and \
            args.nicknames is not None:
        raise SystemExit(
            "Cannot specify both doms.txt and nicknames.txt files")

    if args.nicknames is not None:
        newGeom = NicknameReader.parse(args.nicknames)
    elif args.domsFile is not None:
        newGeom = DomsTxtReader.parse(args.domsFile)
    elif args.geomFile is not None:
        newGeom = None
    else:
        raise SystemExit("Please specify a doms.txt, nicknames.txt" +
                         " or geometry file")

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    if newGeom is not None:
        newGeom.rewrite(False)

    # load in the existing default-dom-geometry file
    if args.oldDefDomGeom is None:
        oldDomGeom = DefaultDomGeometryReader.parse()
    else:
        oldDomGeom = DefaultDomGeometryReader.parse(args.oldDefDomGeom)

    # update geometry info in existing file
    if args.geomFile is not None:
        GeometryFileReader.parse(args.geomFile, defDomGeom=oldDomGeom,
                                 minCoordDiff=args.minCoordDiff)

    # copy new info to existing file
    if newGeom is not None:
        oldDomGeom.update(newGeom, args.verbose)

    # dump the new default-dom-geometry data to sys.stdout
    oldDomGeom.dump()
