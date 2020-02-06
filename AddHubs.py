#!/usr/bin/env python
#
# Create a new run configuration with only the specified hub(s)

from __future__ import print_function

import os
import sys
from utils.Machineid import Machineid

from DAQConfig import DAQConfig, DAQConfigParser
from DAQConfig import DAQConfigException

# find pDAQ's run configuration directory
from locate_pdaq import find_pdaq_config

# save path to configuration directory
CONFIG_DIR = find_pdaq_config()


def parse_args():
    """
    Parse command-line arguments
    Return a tuple containing:
        a boolean indicating if the file should be overwritten if it exists
        the run configuration name
        the list of hub IDs to be removed
    """
    if not os.path.exists(CONFIG_DIR):
        print("Cannot find configuration directory", file=sys.stderr)

    force_create = False
    run_cfg_name = None
    hub_id_list = []

    usage = False
    for arg in sys.argv[1:]:
        if arg == "--force":
            force_create = True
            continue

        if run_cfg_name is None:
            path = os.path.join(CONFIG_DIR, arg)
            if not path.endswith(".xml"):
                path += ".xml"

            if os.path.exists(path):
                run_cfg_name = arg
                continue

        for fld in arg.split(","):
            if fld.endswith("t"):
                try:
                    num = int(fld[:-1])
                    hub_id_list.append(200 + num)
                    continue
                except ValueError:
                    print("Unknown argument \"%s\"" % fld, file=sys.stderr)
                    usage = True
                    continue

            if fld.endswith("i"):
                fld = fld[:-1]

            try:
                num = int(fld)
                hub_id_list.append(num)
                continue
            except ValueError:
                print("Unknown argument \"%s\"" % fld, file=sys.stderr)
                usage = True
                continue

    if not usage and run_cfg_name is None:
        print("No run configuration specified", file=sys.stderr)
        usage = True

    if not usage and len(hub_id_list) == 0:
        print("No hub IDs specified", file=sys.stderr)
        usage = True

    if usage:
        print("Usage: %s runConfig hubId [hubId ...]" % sys.argv[0],
              file=sys.stderr)
        print("  (Hub IDs can be \"6\", \"06\", \"6i\", \"6t\")",
              file=sys.stderr)
        raise SystemExit()

    return (force_create, run_cfg_name, hub_id_list)


def main():
    "Main program"

    hostid = Machineid()
    if not hostid.is_build_host:
        print("-" * 60, file=sys.stderr)
        print("Warning: AddHubs.py should be run on the build machine",
              file=sys.stderr)
        print("-" * 60, file=sys.stderr)

    (force_create, run_cfg_name, hub_id_list) = parse_args()

    new_path = DAQConfig.createOmitFileName(CONFIG_DIR, run_cfg_name,
                                            hub_id_list, keepList=True)
    if os.path.exists(new_path):
        if force_create:
            print("WARNING: Overwriting %s" % new_path, file=sys.stderr)
        else:
            print("WARNING: %s already exists" % new_path, file=sys.stderr)
            print("Specify --force to overwrite this file", file=sys.stderr)
            raise SystemExit()

    try:
        run_cfg = DAQConfigParser.parse(CONFIG_DIR, run_cfg_name)
    except DAQConfigException as config_exp:
        print("WARNING: Error parsing %s" % run_cfg_name, file=sys.stderr)
        raise SystemExit(config_exp)

    if run_cfg is not None:
        new_cfg = run_cfg.omit(hub_id_list, keepList=True)
        if new_cfg is not None:
            with open(new_path, 'w') as fout:
                fout.write(new_cfg)
            print("Created %s" % new_path)


if __name__ == "__main__":
    main()
