#!/usr/bin/env python
#
# Create a new run configuration without one or more hubs

import os
import sys

from ClusterDescription import ClusterDescription
from DAQConfig import DAQConfigException, DAQConfigParser
from DefaultDomGeometry import DefaultDomGeometryReader
from locate_pdaq import find_pdaq_config
from utils.Machineid import Machineid


def add_arguments(parser):
    """
    Parse command-line arguments
    """
    config_dir = find_pdaq_config()
    if not os.path.exists(config_dir):
        raise SystemExit("Cannot find configuration directory")

    parser.add_argument("-c", "--config-dir", dest="config_dir",
                        default=config_dir,
                        help="Directory where run configuration files"
                        " are stored")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="Overwrite existing run configuration file")
    parser.add_argument("-k", "--keep", dest="keep_hubs",
                        action="store_true", default=False,
                        help="Remove all hubs NOT specified by arguments")
    parser.add_argument("-o", "--outname", dest="out_cfg_name",
                        default=None,
                        help="New configuration file name")
    parser.add_argument("runConfig", nargs=1,
                        help="Original run configuration file")
    parser.add_argument("hubOrRack", nargs="+",
                        help="Hub IDs can be \"6\", \"06\", \"6i\", \"6t\","
                        " \"R06\"")


def create_config(run_config, new_path, hub_list, rack_list, keep_hubs=False,
                  force=False):
    """
    Build a new run configuration by removing the hubs and/or rakcks
    Write the new run configuration file to "new_path"
    """
    if run_config is None:
        raise SystemExit("No run configuration!")

    if not new_path.endswith(".xml"):
        new_path += ".xml"
    if os.path.exists(new_path):
        if force:
            print >> sys.stderr, "WARNING: Overwriting %s" % new_path
        else:
            raise SystemExit(("WARNING: %s already exists\n" % new_path) +
                             "Specify --force to overwrite this file")

    # start with the list of hubs
    if hub_list is None:
        final_list = []
    else:
        final_list = hub_list[:]

    # add rack hubs
    if rack_list is not None and len(rack_list) > 0:
        final_list += get_rack_hubs(rack_list)

    # remove hubs from run config
    new_config = run_config.omit(final_list, keep_hubs)
    if new_config is None:
        return None

    # write new configuration
    with open(new_path, 'w') as fd:
        fd.write(new_config)
    return new_path


def create_file_name(config_dir, file_name, hub_id_list, rack_list,
                     keep=False):
    """
    Create a new file name from the original name and the list of hubs.
    """
    basename = os.path.basename(file_name)
    if basename.endswith(".xml"):
        basename = basename[:-4]

    if keep:
        xstr = "-only"
        join_str = "-"
    else:
        xstr = ""
        join_str = "-no"

    racks = ""
    if len(rack_list) > 1:
        rack_names = ["_%02d" % r for r in rack_list]
        rack_names[0] = rack_names[0][1:]
        racks = join_str + "Racks" + ''.join(rack_names)
    elif len(rack_list) == 1:
        racks = join_str + "Rack%02d" % rack_list[0]
    hub_names = [get_hub_name(h) for h in hub_id_list]
    join_list = ["%s%s" % (join_str, hub_name) for hub_name in hub_names]
    xstr = "%s%s%s" % (xstr, racks, ''.join(join_list))

    return os.path.join(config_dir, basename + xstr + ".xml")


def get_hub_name(num):
    """Get the standard representation for a hub number"""
    if num > 0 and num < 100:
        return "%02d" % num
    if num > 200 and num < 220:
        return "%02dt" % (num - 200)
    if ClusterDescription.getClusterFromHostName() == ClusterDescription.SPTS:
        if num >= 1000 and num <= 2099:
            return "%d" % num
    return "?%d?" % num


def get_rack_hubs(rack_list):
    """
    Get the list of hubs attached to all racks in "rack_list"
    """

    # read in default-dom-geometry.xml
    defDomGeom = DefaultDomGeometryReader.parse()

    # build list of hubs
    hubs = []
    for rack in rack_list:
        hubs += defDomGeom.getStringsOnRack(rack)
    return hubs


def main():
    "Main function"
    hostid = Machineid()
    if not hostid.is_build_host():
        print >> sys.stderr, "-" * 60
        print >> sys.stderr, \
            "Warning: RemoveHubs.py should be run on the build machine"
        print >> sys.stderr, "-" * 60

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()
    hub_list, rack_list = parse_hub_rack_strings(p, args.hubOrRack)

    # verify that original run configuration file exists
    if len(args.runConfig) != 1:
        p.error("Unexpected number of runConfig arguments (%d)" %
                len(args.runConfig))
    rc_path = os.path.join(args.config_dir, args.runConfig[0])
    if not rc_path.endswith(".xml"):
        rc_path += ".xml"
    if not os.path.exists(rc_path):
        p.error("Run configuration \"%s\" does not exist" % args.runConfig[0])

    if args.out_cfg_name is None:
        new_path = create_file_name(args.config_dir, rc_path, hub_list,
                                    rack_list, args.keep_hubs)
    else:
        new_path = os.path.join(args.config_dir, args.out_cfg_name)

    try:
        run_config = DAQConfigParser.parse(args.config_dir, rc_path)
    except DAQConfigException as config_except:
        print >> sys.stderr, "WARNING: Error parsing %s" % rc_path
        raise SystemExit(config_except)

    new_path = create_config(run_config, new_path, hub_list, rack_list,
                             keep_hubs=args.keep_hubs, force=args.force)
    if new_path is None:
        print "No hubs/racks removed from %s" % (run_config.basename, )
    else:
        print "Created %s" % (new_path, )


def parse_hub_rack_strings(parser, extra):
    """
    Convert hub/rack strings from command-line into lists of hubs and or racks
    """
    hub_list = []
    rack_list = []

    for arg in extra:
        for substr in arg.split(","):
            if substr.startswith("R"):
                try:
                    num = int(substr[1:])
                    rack_list.append(num)
                except:
                    parser.error("Bad rack specifier \"%s\"" % substr)
                continue

            offset = 0
            if substr.endswith("t"):
                substr = substr[:-1]
                offset = 200
            elif substr.endswith("i"):
                substr = substr[:-1]

            try:
                num = int(substr) + offset
                hub_list.append(num)
            except:
                parser.error("Bad hub specifier \"%s\"" % substr)
            continue

    if len(hub_list) == 0 and len(rack_list) == 0:
        parser.error("No hubs or racks specified")

    return (hub_list, rack_list)


if __name__ == "__main__":
    import argparse

    main()
