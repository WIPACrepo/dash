#!/usr/bin/env python
#
# Split a run configuration into detector quadrants
#
# J. Kelley
# 15 January 2013

from __future__ import print_function

import os

from DefaultDomGeometry import DefaultDomGeometryReader
from DAQConfig import DAQConfigException, DAQConfigParser
from RemoveHubs import create_config, get_hub_name
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
    parser.add_argument("-N", "--noXX_only", dest="noXX_only",
                        action="store_true", default=False,
                        help="Only generate -noXX run configurations")
    parser.add_argument("-P", "--partitions_only", dest="partitions_only",
                        action="store_true", default=False,
                        help="Only generate partition run configurations")
    parser.add_argument("-p", "--print-testdaq", dest="print_testdaq",
                        action="store_true", default=False,
                        help="Print domhubConfig.dat sections for testdaq")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Verbose mode")
    parser.add_argument("runConfig", nargs=1,
                        help="Run configuration file to partition")


def __make_partition_config(run_config, partitions, it_key, ii_key,
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

    hub_list = sorted(partitions[it_key] + partitions[ii_key])

    if verbose:
        print("Generating partition %s" % cfgname)
        print("  using hubs %s" % range_string(hub_list))

    new_name = "%s_%s_partition.xml" % (basename, cfgname)
    if not dry_run:
        final_path = create_config(run_config, hub_list, None,
                                   new_name=new_name, keep_hubs=True,
                                   force=force, verbose=verbose)
    elif verbose:
        print("  writing to %s" % (new_name, ))
    else:
        print("%s: %s" % (new_name, range_string(hub_list)))

    return tstname, hub_list


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
        print("Reading DOM geometry data")

    # read in default-dom-geometry.xml
    def_dom_geom = DefaultDomGeometryReader.parse()

    # get partition definitions
    partitions = def_dom_geom.getPartitions()

    if verbose:
        print("Sanity-checking all partitions")

    # build tuples will all IceTop and In-Ice partition keys
    icetop_keys = ("NORTH", "SOUTH")
    inice_keys = ("NORTHEAST", "NORTHWEST", "SOUTHEAST", "SOUTHWEST")

    # make sure partitions include all strings and stations
    all_icetop = [x for x in range(201, 212)]
    sanity_check(partitions, "IceTop", icetop_keys, all_icetop)
    all_inice = [x for x in range(1, 87)]
    sanity_check(partitions, "InIce", inice_keys, all_inice)

    # fill in superset partitions
    partitions["IINORTH"] = partitions["NORTHEAST"] + partitions["NORTHWEST"]
    partitions["IISOUTH"] = partitions["SOUTHEAST"] + partitions["SOUTHWEST"]
    partitions["INICE"] = partitions["IINORTH"] + partitions["IISOUTH"]

    return partitions


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
        print("=== EXPECTED\n%s" % str(expected))
        print("=== RECEIVED\n%s" % str(testlist))
        raise SystemExit("Bad %s partitions (missing or duplicate hubs)!" %
                         name)


def main():
    import argparse

    op = argparse.ArgumentParser()
    add_arguments(op)
    args = op.parse_args()

    gen_partitions = True
    gen_noXX = True
    if args.partitions_only or args.noXX_only:
        if not args.partitions_only:
            gen_partitions = False
        if not args.noXX_only:
            gen_noXX = False

    if args.verbose:
        print("Finding pDAQ configuration directory")

    # find the pDAQ configuration directory
    config_dir = find_pdaq_config()

    if args.verbose:
        print("Reading run configuration \"%s\"" % args.runConfig[0])

    try:
        run_config = DAQConfigParser.parse(config_dir, args.runConfig[0])
    except DAQConfigException as config_except:
        raise SystemExit(str(args.runConfig) + ": " + str(config_except))

    # map generated configuration names to lists of included hubs
    tstlist = {}

    if gen_partitions:
        # get partition descriptions
        partitions = get_partitions(verbose=args.verbose)

        # get partition descriptions
        for it_key, ii_key in PARTITION_KEYS:
            (tstname, hubs) = __make_partition_config(run_config, partitions,
                                                      it_key, ii_key,
                                                      dry_run=args.dryrun,
                                                      force=args.force,
                                                      verbose=args.verbose)
            if args.print_testdaq:
                tstlist[tstname] = hubs

    if gen_noXX:
        if args.verbose:
            print("Generating noXX versions of %s" % (run_config.basename, ))
        for comp in run_config.components():
            if comp.isHub:
                if not args.dryrun:
                    new_cfg = create_config(run_config, [comp.id, ], None,
                                            force=args.force,
                                            verbose=args.verbose)
                elif args.verbose:
                    print("  writing to %s-no%s" % \
                        (run_config.basename, get_hub_name(comp.id)))
                else:
                    print("%s-no%s" % \
                        (run_config.basename, get_hub_name(comp.id)))

                # XXX not adding noXX config to tstlist

    if args.print_testdaq:
        print("domhubConfig.dat sections:")

        first = True
        for tstname, hubs in list(tstlist.items()):
            if first:
                first = False
            else:
                print("")

            print("\"%s\"" % tstname)

            hubs.sort()
            for hub in hubs:
                if hub < 200:
                    print("sps-ichub%02d" % hub)
                elif hub < 212:
                    print("sps-ithub%02d" % (hub - 200))
                else:
                    return "unknown%02d" % hub


if __name__ == "__main__":
    main()
