#!/usr/bin/env python
#
# Read a list of flasher files and durations from a text file and
# execute a flasher run

import os
import re
import sys

from BaseRun import FlasherScript
from liverun import LiveRun

if __name__ == "__main__":
    import optparse
    import signal

    op = optparse.OptionParser()
    op.add_option("-c", "--daq-config", dest="daqConfig",
                  action="store", default=None,
                  help="DAQ run configuration")
    op.add_option("-d", "--flasher-delay", type="int", dest="flasherDelay",
                  action="store", default=120,
                  help="Initial delay (in seconds) before" + \
                       " flashers are started"),
    op.add_option("-F", "--flasher-list", dest="flasherList",
                  action="store", default=None,
                  help=("File containing pairs of script names and" +
                        " run durations in seconds"))
    op.add_option("-f", "--filter-mode", dest="filterMode",
                  action="store", default="RandomFiltering",
                  help="Filter mode sent to 'livecmd start daq'")
    op.add_option("-n", "--dry-run", dest="dryRun",
                  action="store_true", default=False,
                  help="Don't run commands, just print as they would be run")
    op.add_option("-r", "--run-mode", dest="runMode",
                  action="store", default="TestData",
                  help="Run mode sent to 'livecmd start daq'")
    op.add_option("-v", "--verbose", dest="verbose",
                  action="store_true", default=False,
                  help="Print more details of run transitions")
    op.add_option("-X", "--showCheckOutput", dest="showChkOutput",
                  action="store_true", default=False,
                  help="Show the output of the 'livecmd check' commands")
    op.add_option("-x", "--showCommandOutput", dest="showCmdOutput",
                  action="store_true", default=False,
                  help="Show the output of the deploy and/or run commands")

    opt, args = op.parse_args()

    if opt.daqConfig is None:
        cfg = None
    else:
        cfg = opt.daqConfig

    # list of flashers is either specified with '-'f or is one of two arguments
    flashName = None
    flashPairs = None
    if opt.flasherList is not None:
        flashName = opt.flasherList
        flashPairs = FlasherScript.parse(opt.flasherList)
        if cfg is None:
            if len(args) == 0:
                raise SystemExit("No run configuration specified")
            cfg = args[0]
    elif len(args) == 1:
        if flashName is None and cfg is not None:
            flashName = args[0]
            flashPairs = FlasherScript.parse(args[0])
        elif cfg is None and flashName is not None:
            cfg = args[0]
    elif len(args) == 2:
        try:
            flashPairs = FlasherScript.parse(args[0])
            flashName = args[0]
            cfg = args[1]
        except:
            try:
                flashPairs = FlasherScript.parse(args[1])
                flashName = args[1]
                cfg = args[0]
            except:
                raise SystemExit("Unknown arguments (%s)" % str(args))

    if flashPairs is None:
        raise SystemExit("Please specify the list of flasher files" +
                         " and durations")
    elif cfg is None:
        raise SystemExit("Please specify the run configuration")

    logName = os.path.splitext(flashName)[0] + ".log"

    showCmd = True
    runmgr = LiveRun(showCmd, opt.showCmdOutput, dryRun=opt.dryRun,
                     logfile=logName)

    if sys.version_info > (2, 3):
        from DumpThreads import DumpThreadsOnSignal
        DumpThreadsOnSignal(fd=sys.stderr)

    # stop existing runs gracefully on ^C
    #
    signal.signal(signal.SIGINT, runmgr.stopOnSIGINT)

    runmgr.run(None, cfg, 0, flashPairs, flasherDelay=opt.flasherDelay,
               runMode=opt.runMode, filterMode=opt.filterMode,
               verbose=opt.verbose)
