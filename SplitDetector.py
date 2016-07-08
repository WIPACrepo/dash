#!/usr/bin/env python
#
# Split a run configuration into detector quadrants
#
# J. Kelley
# 15 January 2013


import os

from DefaultDomGeometry import DefaultDomGeometryReader
from DAQConfig import DAQConfigException, DAQConfigParser
from RemoveHubs import create_config
from locate_pdaq import find_pdaq_config


# list of icetop and in-ice keys used to build each partition
PARTITION_KEYS = (
    ("NORTH", "INICE"),
    ("SOUTH", "INICE"),
    ("NORTH", "IINORTH"),
    ("SOUTH", "IISOUTH"),
    ("NORTH", "NORTHEAST"),
    ("NORTH", "NORTHWEST"),
    ("SOUTH", "SOUTHEAST"),
    ("SOUTH", "SOUTHWEST"),
)


class SplitException(Exception):
    pass


def add_arguments(parser):
    parser.add_argument("-d", "--dry-run", dest="dryrun",
                        action="store_true", default=False,
                        help="Dry run (do not actually create configurations)")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="Overwrite existing configuration file(s)")
    parser.add_argument("-p", "--print-testdaq", dest="print_testdaq",
                        action="store_true", default=False,
                        help="Print domhubConfig.dat sections for testdaq")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Verbose mode")
    parser.add_argument("runConfig", nargs=1,
                        help="Run configuration file to partition")


def get_partitions(verbose=False):
    """
    Get lists of hubs associated with each partition.
    Partitions "NORTH" and "SOUTH" should include all IceTop hubs.
    Partitions "NORTHEAST", "NORTHWEST", "SOUTHEAST", and "SOUTHWEST" should
    include all In-Ice hubs.
    Partitions "IINORTH" and "IISOUTH" are supersets of the In-Ice "NORTH*"
    and "SOUTH*" partitions.
    Partition "INICE" is a superset of all In-Ice hubs.
    """

    if verbose:
        print "Reading DOM geometry data"

    # read in default-dom-geometry.xml
    def_dom_geom = DefaultDomGeometryReader.parse()

    # get partition definitions
    partitions = def_dom_geom.getPartitions()

    if verbose:
        print "Sanity-checking all partitions"

    # build tuples will all IceTop and In-Ice partition keys
    icetop_keys = ("NORTH", "SOUTH")
    inice_keys = ("NORTHEAST", "NORTHWEST", "SOUTHEAST", "SOUTHWEST")

    # make sure partitions include all strings and stations
    all_icetop = [x for x in xrange(201, 212)]
    sanity_check(partitions, "IceTop", icetop_keys, all_icetop)
    all_inice = [x for x in xrange(1, 87)]
    sanity_check(partitions, "InIce", inice_keys, all_inice)

    # fill in superset partitions
    partitions["IINORTH"] = partitions["NORTHEAST"] + partitions["NORTHWEST"]
    partitions["IISOUTH"] = partitions["SOUTHEAST"] + partitions["SOUTHWEST"]
    partitions["INICE"] = partitions["IINORTH"] + partitions["IISOUTH"]

    return partitions


def main():
    import argparse

    op = argparse.ArgumentParser()
    add_arguments(op)
    args = op.parse_args()

    if args.verbose:
        print "Finding pDAQ configuration directory"

    # find the pDAQ configuration directory
    config_dir = find_pdaq_config()

    if args.verbose:
        print "Reading run configuration \"%s\"" % args.runConfig[0]

    try:
        run_config = DAQConfigParser.parse(config_dir, args.runConfig[0])
    except DAQConfigException as config_except:
        raise SystemExit(str(args.runConfig) + ": " + str(config_except))

    partitions = get_partitions(verbose=args.verbose)

    tstlist = []
    for it_key, ii_key in PARTITION_KEYS:
        (tstname, hubs) = make_new_config(run_config, config_dir, partitions,
                                          it_key, ii_key, dry_run=args.dryrun,
                                          force=args.force,
                                          verbose=args.verbose)
        if args.print_testdaq:
            tstlist.append((tstname, hubs))

    if args.print_testdaq:
        print "domhubConfig.dat sections:"

        first = True
        for tstname, hubs in tstlist:
            if first:
                first = False
            else:
                print ""

            print "\"%s\"" % tstname

            hubs.sort()
            for hub in hubs:
                if hub < 200:
                    print "sps-ichub%02d" % hub
                elif hub < 212:
                    print "sps-ithub%02d" % (hub - 200)
                else:
                    return "unknown%02d" % hub


def make_new_config(run_config, config_dir, partitions, it_key, ii_key,
                    dry_run=False, force=False, verbose=False):
    if it_key != "NORTH" and it_key != "SOUTH":
        raise SplitException("Bad IceTop key \"%s\"" % it_key)

    basename = run_config.filename
    if basename.endswith(".xml"):
        basename = basename[:-4]

    cfgname = "IceTop" + it_key
    tstname = "icetop_" + it_key.lower()

    if ii_key == "INICE":
        cfgname += ""
        tstname += "_inice"
    elif ii_key.startswith("II"):
        cfgname += "_InIce" + ii_key[2:]
        tstname += "_inice_" + ii_key[2:].lower()
    else:
        cfgname += "_InIce" + ii_key
        tstname += "_inice_" + ii_key.lower()

    hub_list = partitions[it_key] + partitions[ii_key]
    hub_list.sort()

    if verbose:
        print "Generating partition %s" % cfgname
        print "  using hubs %s" % range_string(hub_list)

    path = os.path.join(config_dir, basename + "_" + cfgname + "_partition.xml")
    if not dry_run:
        create_config(run_config, path, hub_list, None, keep_hubs=True,
                      force=force)
    elif verbose:
        print "  writing to %s" % path
    else:
        print "%s: %s" % (path, range_string(hub_list))

    return tstname, hub_list


def range_string(hub_list):
    """
    Create a concise string from a list of numbers
    (e.g. [1, 3, 4, 5, 7, 8, 9] will return "1,3-5,7-9")
    """
    prevHub = None
    rangeStr = ""
    for hub in sorted(hub_list):
        if prevHub is None:
            rangeStr += "%d" % hub
        elif hub == prevHub + 1:
            if not rangeStr.endswith("-"):
                rangeStr += "-"
        else:
            if rangeStr.endswith("-"):
                rangeStr += "%d" % prevHub
            rangeStr += ",%d" % hub
        prevHub = hub
    if prevHub is not None and rangeStr.endswith("-"):
        rangeStr += "%d" % prevHub
    return rangeStr


def sanity_check(partitions, name, keys, expected):
    """
    If the hubs from the partitions listed in "keys" do not match the
    hubs in "expected", complain and exit
    """

    # first make sure the individual partitions don't overlap
    for k1 in keys:
        for k2 in keys:
            if k1 == k2:
                continue
            overlap = [hub for hub in partitions[k1] if hub in partitions[k2]]
            if len(overlap) > 0:
                raise SystemExit("Partitions \"%s\" and \"%s\" both contain"
                                 " hubs %s" % (k1, k2, overlap))

    # build a list containing all the hubs from the individual partitions
    testlist = []
    for part in keys:
        if part not in partitions:
            raise SystemExit("No %s %s partition found" % (name, part))

        testlist += partitions[part]
    testlist.sort()

    # die if the final list doesn't contain all the expected hubs
    if testlist != expected:
        print "=== EXPECTED\n%s" % str(expected)
        print "=== RECEIVED\n%s" % str(testlist)
        raise SystemExit("Bad %s partitions (missing or duplicate hubs)!" %
                         name)


if __name__ == "__main__":
    main()
