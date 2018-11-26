#!/usr/bin/env python
#
# Read a list of flasher files and durations from a text file and
# execute a flasher run

import os
import sys

from BaseRun import FlasherScript
from liverun import LiveRun
from utils.Machineid import Machineid


def add_arguments(parser):
    parser.add_argument("-c", "--daq-config", dest="daqConfig",
                        help="DAQ run configuration")
    parser.add_argument("-d", "--flasher-delay", type=int, dest="flasherDelay",
                        default=120,
                        help="Initial delay (in seconds) before"
                        " flashers are started"),
    parser.add_argument("-F", "--flasher-list", dest="flasherList",
                        help=("File containing pairs of script names and"
                              " run durations in seconds"))
    parser.add_argument("-f", "--filter-mode", dest="filterMode",
                        default="RandomFiltering",
                        help="Filter mode sent to 'livecmd start daq'")
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help=("Disable checking the host type"
                              " for run permission"))
    parser.add_argument("-n", "--dry-run", dest="dryRun",
                        action="store_true", default=False,
                        help=("Don't run commands, just print as they"
                              " would be run"))
    parser.add_argument("-r", "--run-mode", dest="runMode",
                        default="TestData",
                        help="Run mode sent to 'livecmd start daq'")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print more details of run transitions")
    parser.add_argument("-X", "--showCheckOutput", dest="showChkOutput",
                        action="store_true", default=False,
                        help="Show the output of the 'livecmd check' commands")
    parser.add_argument("-x", "--showCommandOutput", dest="showCmdOutput",
                        action="store_true", default=False,
                        help=("Show the output of the deploy and/or"
                              " run commands"))
    parser.add_argument("flashName", nargs="?")
    parser.add_argument("config", nargs="?")


def flash(args):
    if args.daqConfig is None:
        cfg = None
    else:
        cfg = args.daqConfig

    # list of flashers is either specified with '-f' or is one or two arguments
    flashName = None
    flashPairs = None
    if args.flasherList is not None:
        flashName = args.flasherList
        flashPairs = FlasherScript.parse(args.flasherList)
        if cfg is None:
            if args.flashName is None:
                raise SystemExit("No run configuration specified")
            cfg = args.flashName
    elif args.flashName is not None and args.config is None:
        if flashName is None and cfg is not None:
            flashName = args.flashName
            flashPairs = FlasherScript.parse(args.flashName)
        elif cfg is None and flashName is not None:
            cfg = args.flashName
    elif args.config is not None:
        try:
            flashPairs = FlasherScript.parse(args.flashName)
            flashName = args.flashName
            cfg = args.config
        except:
            try:
                flashPairs = FlasherScript.parse(args.config)
                flashName = args.config
                cfg = args.flashName
            except:
                raise SystemExit("Unknown arguments \"%s\" and/or \"%s\"" %
                                 (args.flashName, args.config))

    if flashPairs is None:
        raise SystemExit("Please specify the list of flasher files" +
                         " and durations")
    elif cfg is None:
        raise SystemExit("Please specify the run configuration")

    logName = os.path.splitext(flashName)[0] + ".log"

    runmgr = LiveRun(showCmd=True, showCmdOutput=args.showCmdOutput,
                     dryRun=args.dryRun, logfile=logName)

    if sys.version_info > (2, 3):
        from DumpThreads import DumpThreadsOnSignal
        DumpThreadsOnSignal(fd=sys.stderr)

    # stop existing runs gracefully on ^C
    #
    signal.signal(signal.SIGINT, runmgr.stopOnSIGINT)

    runmgr.run(None, cfg, 0, flashPairs, flasherDelay=args.flasherDelay,
               runMode=args.runMode, filterMode=args.filterMode,
               verbose=args.verbose)


if __name__ == "__main__":
    import argparse
    import signal

    op = argparse.ArgumentParser()
    add_arguments(op)

    args = op.parse_args()

    if not args.nohostcheck:
        hostid = Machineid()
        if not (hostid.is_control_host() or
                (hostid.is_unknown_host() and hostid.is_unknown_cluster())):
            # you should either be a control host or a totally unknown host
            raise SystemExit("Are you sure you are running flashers"
                             " on the correct host?")

    flash(args)
