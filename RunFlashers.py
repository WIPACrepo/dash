#!/usr/bin/env python
"""
`pdaq flash` script which reads a list of flasher files and durations from a
text file and executes a flasher run
"""


import os
import sys

from BaseRun import FlasherScript
from liverun import LiveRun
from utils.Machineid import Machineid


def add_arguments(parser):
    "Add command-line arguments"

    parser.add_argument("-c", "--daq-config", dest="daqConfig",
                        help="DAQ run configuration")
    parser.add_argument("-d", "--flasher-delay", type=int, dest="delay",
                        default=120,
                        help=("Initial delay (in seconds) before"
                              " flashers are started"))
    parser.add_argument("-F", "--flasher-list", dest="flasher_list",
                        help=("File containing pairs of script names and"
                              " run durations in seconds"))
    parser.add_argument("-f", "--filter-mode", dest="filter_mode",
                        default="RandomFiltering",
                        help="Filter mode sent to 'livecmd start daq'")
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help=("Disable checking the host type"
                              " for run permission"))
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help=("Don't run commands, just print as they"
                              " would be run"))
    parser.add_argument("-r", "--run-mode", dest="run_mode",
                        default="TestData",
                        help="Run mode sent to 'livecmd start daq'")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print more details of run transitions")
    parser.add_argument("-X", "--show_check_output", dest="show_check_output",
                        action="store_true", default=False,
                        help="Show the output of the 'livecmd check' commands")
    parser.add_argument("-x", "--show_command_output",
                        dest="show_command_output",
                        action="store_true", default=False,
                        help=("Show the output of the deploy and/or"
                              " run commands"))
    parser.add_argument("flash_name", nargs="?")
    parser.add_argument("config", nargs="?")


def flash(args):
    if args.daqConfig is None:
        cfg = None
    else:
        cfg = args.daqConfig

    # list of flashers is either specified with '-f' or is one or two arguments
    flash_name = None
    flash_pairs = None
    if args.flasher_list is not None:
        flash_name = args.flasher_list
        flash_pairs = FlasherScript.parse(args.flasher_list)
        if cfg is None:
            if args.flash_name is None:
                raise SystemExit("No run configuration specified")
            cfg = args.flash_name
    elif args.flash_name is not None and args.config is None:
        if flash_name is None and cfg is not None:
            flash_name = args.flash_name
            flash_pairs = FlasherScript.parse(args.flash_name)
        elif cfg is None and flash_name is not None:
            cfg = args.flash_name
    elif args.config is not None:
        try:
            flash_pairs = FlasherScript.parse(args.flash_name)
            flash_name = args.flash_name
            cfg = args.config
        except:  # pylint: disable=bare-except
            try:
                flash_pairs = FlasherScript.parse(args.config)
                flash_name = args.config
                cfg = args.flash_name
            except:
                raise SystemExit("Unknown arguments \"%s\" and/or \"%s\"" %
                                 (args.flash_name, args.config))

    if flash_pairs is None:
        raise SystemExit("Please specify the list of flasher files" +
                         " and durations")
    elif cfg is None:
        raise SystemExit("Please specify the run configuration")

    log_name = os.path.splitext(flash_name)[0] + ".log"

    runmgr = LiveRun(show_commands=True,
                     show_command_output=args.show_command_output,
                     dry_run=args.dry_run, logfile=log_name)

    if sys.version_info > (2, 3):
        from DumpThreads import DumpThreadsOnSignal
        DumpThreadsOnSignal(file_handle=sys.stderr)

    # stop existing runs gracefully on ^C
    #
    signal.signal(signal.SIGINT, runmgr.stop_on_sigint)

    runmgr.run(None, cfg, 0, flash_pairs, flasher_delay=args.delay,
               run_mode=args.run_mode, filter_mode=args.filter_mode,
               verbose=args.verbose)


def main():
    "Main program"

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    if not args.nohostcheck:
        hostid = Machineid()
        if not (hostid.is_control_host or
                (hostid.is_unknown_host and hostid.is_unknown_cluster)):
            # you should either be a control host or a totally unknown host
            raise SystemExit("Are you sure you are running flashers"
                             " on the correct host?")

    flash(args)


if __name__ == "__main__":
    import argparse
    import signal

    main()
