#!/usr/bin/env python
#
# Wrapper to RemoveHubs.py that will split a run configuration into
# detector quadrants.
#
# J. Kelley
# 15 January 2013
#
#-------------------------------------------------------------------

import sys
import os
import getopt

#-------------------------------------------------------------------
# Definition of detector pieces, in terms of domhubs
#
# Warning -- if this is changed, you should also update domhubConfig.dat
# on testdaq01 to match.  You can print the domhubConfig.dat sections with
# the -p option.
#

ICETOP_NORTH = [201, 202, 203, 205, 206, 208]
ICETOP_SOUTH = [204, 207, 209, 210, 211]

INICE_NORTHEAST = [73, 74,
                   65, 66, 67,
                   56, 57, 58, 59,
                   47, 48, 49, 50,
                   38, 39, 40,
                   28, 29, 30,
                   21]

INICE_NORTHWEST = [75, 76, 77, 78,
                   68, 69, 70, 71, 72,
                   60, 61, 62, 63, 64,
                   52, 53, 54, 55,
                   44]

INICE_SOUTHEAST = [45, 46,
                   86, 81, 82,
                   35, 36, 37,
                   85, 79, 80, 83,
                   84,
                   26, 27,
                   18, 19, 20,
                   10, 11, 12, 13,
                   3, 4, 5, 6]

INICE_SOUTHWEST = [51,
                   41, 42, 43,
                   31, 32, 33, 34,
                   22, 23, 24, 25,
                   14, 15, 16, 17,
                   7, 8, 9,
                   1, 2]

INICE_NORTH = INICE_NORTHEAST + INICE_NORTHWEST
INICE_SOUTH = INICE_SOUTHEAST + INICE_SOUTHWEST

# Master lists for checking above partitions
INICE = [x for x in xrange(1, 87)]
ICETOP = [x for x in xrange(201, 212)]

# RemoveHubs script
REMOVEHUBSCMD = "RemoveHubs.py"

#-------------------------------------------------------------------


def hub2Host(h):
    """ Convert a hub number to SPS hostname """
    if h < 200:
        return "sps-ichub%02d" % (h)
    elif h < 212:
        return "sps-ithub%02d" % (h - 200)
    else:
        return "unknown"


def makeNewConfig(cfgName, suffix, hubs, dryrun=False, force=False):
    """
    Generate a new partial-detector configuration from
    run config cfgName, adding the suffix before the
    file extension, and removing DOMHubs in hubs.
    """
    removeHubStr = ""
    allHubs = INICE + ICETOP
    # Determine which hubs to remove
    for h in allHubs:
        if h not in hubs:
            if h < 200:
                removeHubStr += str(h)
            else:
                removeHubStr += str(h - 200) + "t"
            removeHubStr += " "

    # Create new configuration filename
    suffix += "_partition"
    if cfgName.endswith(".xml"):
        newName = cfgName.rstrip(".xml")
        newName += "_" + suffix + ".xml"
    else:
        newName = cfgName + "_" + suffix + ".xml"

    # Finally -- execute the hub removal script
    # This is not very Pythonic, admittedly
    if force:
        opts = " --force -o " + newName
    else:
        opts = " -o " + newName
    cmd = REMOVEHUBSCMD + opts + " " + cfgName + " " + removeHubStr
    if not dryrun:
        os.system(cmd)
    else:
        print "Would execute: ", cmd


def usage():
    """ Print program usage """
    print "Usage: %s [-fpvd] run_config.xml" % (sys.argv[0])
    print "    -f    force overwrite configurations"
    print "    -v    verbose mode"
    print "    -d    dry run (do not actually create configurations)"
    print "    -p    print domhubConfig.dat sections for testdaq"


def main():
    """
    Split an IceCube run configuration into subdetector
    pieces (for emergency configs, calibration runs, etc.)
    """
    #---------------------------------------------------
    # Parse command-line options
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hpvdf", [
            "help", "print", "verbose", "dryrun", "force"
        ])
    except getopt.GetoptError as err:
        print str(err)
        usage()
        sys.exit(2)

    printHubConfig = False
    verbose = False
    dryrun = False
    force = False
    for o, _ in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-p", "--print"):
            printHubConfig = True
        elif o in ("-v", "--verbose"):
            verbose = True
        elif o in ("-d", "--dryrun"):
            dryrun = True
        elif o in ("-f", "--force"):
            force = True
        else:
            assert False, "unhandled option"

    if len(args) != 1:
        usage()
        sys.exit(2)

    cfgName = args[0]

    #---------------------------------------------------
    # Sanity-check the detector regions
    icetopTest = ICETOP_NORTH + ICETOP_SOUTH
    icetopTest.sort()

    if icetopTest != ICETOP:
        print >> sys.stderr, \
              "ERROR: IceTop divisions bad (missing or duplicate hubs)!"
        sys.exit(-1)

    iniceTest = INICE_NORTHEAST + INICE_NORTHWEST + \
                INICE_SOUTHEAST + INICE_SOUTHWEST
    iniceTest.sort()

    if iniceTest != INICE:
        print >> sys.stderr, \
              "ERROR: in-ice divisions bad (missing or duplicate hubs)!"
        sys.exit(-1)

    #---------------------------------------------------
    # List of partitions to create
    partitionList = [INICE + ICETOP_NORTH,
                     INICE + ICETOP_SOUTH,
                     INICE_NORTH + ICETOP_NORTH,
                     INICE_SOUTH + ICETOP_SOUTH,
                     INICE_NORTHEAST + ICETOP_NORTH,
                     INICE_NORTHWEST + ICETOP_NORTH,
                     INICE_SOUTHEAST + ICETOP_SOUTH,
                     INICE_SOUTHWEST + ICETOP_SOUTH]

    # Filename suffix to append at the end of the configuration name
    suffixList = ["IceTopNORTH",
                  "IceTopSOUTH",
                  "IceTopNORTH_InIceNORTH",
                  "IceTopSOUTH_InIceSOUTH",
                  "IceTopNORTH_InIceNORTHEAST",
                  "IceTopNORTH_InIceNORTHWEST",
                  "IceTopSOUTH_InIceSOUTHEAST",
                  "IceTopSOUTH_InIceSOUTHWEST"]

    # domhubConfig.dat partition name
    domhubList = ["icetop_north_inice",
                  "icetop_south_inice",
                  "icetop_north_inice_north",
                  "icetop_south_inice_south",
                  "icetop_north_inice_northeast",
                  "icetop_north_inice_northwest",
                  "icetop_south_inice_southeast",
                  "icetop_south_inice_southwest"]

    # Create the new configurations
    for (hubs, suffix) in zip(partitionList, suffixList):
        if verbose:
            print "Generating partition", suffix
            print "  Removing hubs", hubs
        makeNewConfig(cfgName, suffix, hubs, dryrun=dryrun, force=force)

    # Print new section definitions for domhubConfig.dat on testdaq01
    if printHubConfig:
        print "domhubConfig.dat sections:"
        for (hubs, domhubName) in zip(partitionList, domhubList):
            print "\"%s\"" % (domhubName)
            hubs.sort()
            for h in hubs:
                print hub2Host(h)
            print ""

if __name__ == "__main__":
    main()
