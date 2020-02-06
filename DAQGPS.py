#!/usr/bin/env python

# GPSCheck.py
# John Jacobsen, NPX Designs, Inc., jacobsen\@npxdesigns.com
# Started: Fri Jun  1 15:57:10 2007

from __future__ import print_function

import sys

from DAQConfig import DAQConfigParser
from DAQConfigExceptions import DAQConfigException
from ParallelShell import ParallelShell


def main():
    "Main program"
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("-c", "--config-name",
                   dest="clusterConfigName",
                   help="REQUIRED: Configuration name")
    p.add_argument("-n", "--dry-run", dest="dry_run",
                   action="store_true", default=False,
                   help="Don't actually run DAQGPS - just print what" +
                   " would be done")
    p.add_argument("-z", "--no-schema-validation", dest="validation",
                   action="store_false", default=True,
                   help="Disable schema validation of xml config files")

    args = p.parse_args()

    try:
        config = DAQConfigParser.\
            get_cluster_configuration(args.clusterConfigName,
                                      validate=args.validation)
    except DAQConfigException as e:
        print("Configuration file problem:\n%s" % e, file=sys.stderr)
        raise SystemExit

    if args.doList:
        raise SystemExit

    hublist = config.get_hub_nodes()

    cmds = ParallelShell(dry_run=args.dry_run, timeout=20)
    ids = {}
    for hub in hublist:
        # FIXME - actually implement the right thing here
        cmd = "ssh %s readgps -h" % hub
        ids[hub] = (cmds.add(cmd))

    cmds.start()
    cmds.wait()

    for hub in hublist:
        print("Hub %s: " % hub, end=' ')
        result = cmds.getResult(ids[hub])
        result = result.rstrip()
        print(result)

        # Parse template:
        # 2 pairs plugged, 2 powered; 4 DOMs communicating, 4 in iceboot
        # match = re.search(r'(\d+) pairs plugged, (\d+) powered;
        #                   (\d+) DOMs communicating, (\d+) in iceboot',
        #                   result)


if __name__ == "__main__":
    main()
