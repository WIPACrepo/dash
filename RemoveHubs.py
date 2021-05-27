#!/usr/bin/env python
"""
`pdaq removehubs` script to create a new run configuration file by
removing hubs or racks from the original configuration
"""

from __future__ import print_function

import os
import sys

from DAQConfig import DAQConfigException, DAQConfigParser
from DefaultDomGeometry import DefaultDomGeometryReader
from locate_pdaq import find_pdaq_config
from utils.Machineid import Machineid


def add_arguments(parser):
    "Add command-line arguments"

    config_dir = find_pdaq_config()
    if not os.path.exists(config_dir):
        raise SystemExit("Cannot find configuration directory")

    parser.add_argument("-c", "--config-dir", dest="config_dir",
                        default=config_dir,
                        help=("Directory where run configuration files"
                              " are stored"))
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="Overwrite existing run configuration file")
    parser.add_argument("-k", "--keep", dest="keep_hubs",
                        action="store_true", default=False,
                        help="Remove all hubs NOT specified by arguments")
    parser.add_argument("-o", "--outname", dest="out_cfg_name",
                        default=None,
                        help="New configuration file name")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Verbose mode")
    parser.add_argument("run_config", nargs=1,
                        help="Original run configuration file")
    parser.add_argument("hubOrRack", nargs="+",
                        help=("Hub IDs can be \"6\", \"06\", \"6i\", \"6t\","
                              " \"R06\""))


def __create_file_name(config_dir, file_name, hub_id_list, rack_list,
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
    if rack_list is not None:
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


def create_config(run_config, hub_list, rack_list, new_name=None,
                  keep_hubs=False, force=False, verbose=False):
    """
    Build a new run configuration by removing the hubs and/or racks
    Write the new run configuration file to "new_path"
    """
    if run_config is None:
        raise SystemExit("No run configuration!")

    if new_name is None:
        new_path = __create_file_name(run_config.configdir,
                                      run_config.basename, hub_list, rack_list,
                                      keep_hubs)
    else:
        if new_name.startswith(run_config.configdir):
            new_path = new_name
        else:
            new_path = os.path.join(run_config.configdir, new_name)
        if not new_path.endswith(".xml"):
            new_path += ".xml"

    if os.path.exists(new_path):
        if force:
            print("WARNING: Overwriting %s" % new_path, file=sys.stderr)
        else:
            raise SystemExit(("WARNING: %s already exists\n" % new_path) +
                             "Specify --force to overwrite this file")

    # start with the list of hubs
    if hub_list is None:
        final_list = []
    else:
        final_list = hub_list[:]

    # add rack hubs
    # pylint: disable=len-as-condition
    if rack_list is not None and len(rack_list) > 0:
        final_list += get_rack_hubs(rack_list)

    # remove hubs from run config
    new_config = run_config.omit(final_list, keep_hubs)
    if new_config is None:
        if verbose:
            print("No hubs/racks removed from %s" % (run_config.basename, ))
        return None

    # write new configuration
    with open(new_path, 'w') as fout:
        fout.write(new_config)
    if verbose:
        print("Created %s" % (new_path, ))
    return new_path


def get_hub_name(num):
    """Get the standard representation for a hub number"""
    if 0 < num < 100:
        return "%02d" % num
    if 200 < num < 220:
        return "%02dt" % (num - 200)
    mid = Machineid()
    if mid.is_spts_cluster:
        if 1000 <= num <= 2099:
            return "%d" % num
    return "?%d?" % num


def get_rack_hubs(rack_list):
    """
    Get the list of hubs attached to all racks in "rack_list"
    """

    # read in default-dom-geometry.xml
    def_dom_geom = DefaultDomGeometryReader.parse()

    # build list of hubs
    hubs = []
    for rack in rack_list:
        hubs += def_dom_geom.strings_on_rack(rack)
    return hubs


def main():
    "Main program"
    hostid = Machineid()
    if not hostid.is_build_host:
        print("-" * 60, file=sys.stderr)
        print("Warning: RemoveHubs.py should be run on the build machine",
              file=sys.stderr)
        print("-" * 60, file=sys.stderr)

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    remove_hubs(args)


def parse_hub_rack_strings(extra):
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
                    raise SystemExit("Bad rack specifier \"%s\"" % substr)
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
                raise SystemExit("Bad hub specifier \"%s\"" % substr)
            continue

    # pylint: disable=len-as-condition
    if len(hub_list) == 0 and len(rack_list) == 0:
        raise SystemExit("No hubs or racks specified")

    return (hub_list, rack_list)


def remove_hubs(args):
    "Remove hubs/racks from a run configuration file"

    hub_list, rack_list = parse_hub_rack_strings(args.hubOrRack)

    # verify that original run configuration file exists
    if len(args.run_config) != 1:
        raise SystemExit("Unexpected number of runConfig arguments (%d)" %
                         (len(args.run_config), ))
    rc_path = os.path.join(args.config_dir, args.run_config[0])
    if not rc_path.endswith(".xml"):
        rc_path += ".xml"
    if not os.path.exists(rc_path):
        raise SystemExit("Run configuration \"%s\" does not exist" %
                         (args.run_config[0], ))

    try:
        run_config = DAQConfigParser.parse(args.config_dir, rc_path)
    except DAQConfigException as config_except:
        print("WARNING: Error parsing %s" % rc_path, file=sys.stderr)
        raise SystemExit(config_except)

    _ = create_config(run_config, hub_list, rack_list,
                      new_name=args.out_cfg_name, keep_hubs=args.keep_hubs,
                      force=args.force, verbose=args.verbose)


if __name__ == "__main__":
    import argparse

    main()
