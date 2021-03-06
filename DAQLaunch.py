#!/usr/bin/env python
"""
`pdaq launch` script used to start/stop the detector
"""

# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

from __future__ import print_function

import os
import subprocess
import sys
import traceback

from utils.Machineid import Machineid

from ComponentManager import ComponentManager
from DAQConfig import DAQConfigParser
from DAQConfigExceptions import DAQConfigException
from DAQConst import DAQPort
from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from scmversion import get_scmversion_str


# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()


class ConsoleLogger(object):
    "Console logger"
    def __init__(self):
        "Create a console logger"
        return

    @classmethod
    def error(cls, msg):
        "Print an error message"
        print(msg, file=sys.stderr)

    @classmethod
    def info(cls, msg):
        "Print an informational message"
        print(msg)


def add_arguments_both(parser):
    "Add arguments which apply to both 'pdaq kill' and 'pdaq launch'"

    parser.add_argument("-9", "--kill-kill", dest="kill_with_9",
                        action="store_true", default=False,
                        help="Kill everything with extreme (-9) prejudice")
    parser.add_argument("-C", "--cluster-desc", dest="cluster_desc",
                        help="Cluster description name.")
    parser.add_argument("-S", "--server-kill", dest="serverKill",
                        action="store_true", default=False,
                        help="Kill all the components known by the server")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="kill components even if there is an active run")
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help=("Disable checking the host type for"
                              " run permission"))
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help="\"Dry run\" only, don't actually do anything")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Log output for all components to terminal")
    parser.add_argument("-z", "--no-schema-validation", dest="validate",
                        action="store_false", default=True,
                        help=("Disable schema validation of xml"
                              " configuration files"))


def add_arguments_kill(_):
    "Add arguments which only apply to 'pdaq kill'"
    return


def add_arguments_launch(parser, config_as_arg=True):
    "Add arguments which only apply to 'pdaq launch'"

    if config_as_arg:
        parser.add_argument("-c", "--config-name", dest="config_name",
                            help="Configuration name")
    else:
        parser.add_argument("config_name", nargs="?",
                            help="Run configuration name")

    parser.add_argument("-F", "--no-force-restart", dest="force_restart",
                        action="store_false", default=True,
                        help=("Do not force healthy components to restart at"
                              " run end"))
    parser.add_argument("-e", "--event-check", dest="event_check",
                        action="store_true", default=False,
                        help="Event builder will validate events")
    parser.add_argument("-k", "--kill-only", dest="killOnly",
                        action="store_true", default=False,
                        help="Kill pDAQ components, don't restart")
    parser.add_argument("-s", "--skip-kill", dest="skipKill",
                        action="store_true", default=False,
                        help="Don't kill anything, just launch")


def add_arguments_old(parser):
    "Add backward compatibility arguments"
    parser.add_argument("-l", "--list-configs", dest="doList",
                        action="store_true", default=False,
                        help="List available configs")


def check_arguments(args):
    "Warn about ignored/incompatible arguments"
    ignored = []
    if args.killOnly:
        if args.skipKill:
            raise SystemExit("Cannot specify both -k(illOnly) and -s(kipKill")
        if args.config_name is not None:
            ignored.append("--config-name")
        if args.event_check:
            ignored.append("--event-check")
    elif args.skipKill:
        if args.kill_with_9:
            ignored.append("--kill-kill")
        if args.force:
            ignored.append("--force")
        if args.serverKill:
            ignored.append("--server-kill")
    if len(ignored) > 0:  # pylint: disable=len-as-condition
        print("Ignoring " + ", ".join(ignored), file=sys.stderr)


def check_detector_state():
    "If there are active runsets, print them to the console and exit"
    (runsets, active) = ComponentManager.count_active_runsets()
    if active > 0:
        if len(runsets) == 1:
            plural = ''
        else:
            plural = 's'
        print('Found %d active runset%s:' % (len(runsets), plural),
              file=sys.stderr)
        for rid in list(runsets.keys()):
            print("  %d: %s" % (rid, runsets[rid]), file=sys.stderr)
        raise SystemExit('To force a restart, rerun with the --force option')


def kill(config_dir, logger, args=None):
    "Kill the components specified by the run configuration"
    if args is None:
        cluster_desc = None
        validate = None
        server_kill = None
        verbose = None
        dry_run = None
        kill_with_9 = None
        force = None
    else:
        cluster_desc = args.cluster_desc
        validate = args.validate
        server_kill = args.serverKill
        verbose = args.verbose
        dry_run = args.dry_run
        kill_with_9 = args.kill_with_9
        force = args.force

    comps = ComponentManager.get_active_components(cluster_desc,
                                                   config_dir=config_dir,
                                                   validate=validate,
                                                   use_cnc=server_kill,
                                                   logger=logger)

    if comps is not None:
        kill_cnc = True

        ComponentManager.kill(comps, verbose=verbose, dry_run=dry_run,
                              kill_cnc=kill_cnc, kill_with_9=kill_with_9,
                              logger=logger)

    if force:
        print("Remember to run 'pdaq queuelogs' to recover any orphaned data",
              file=sys.stderr)


def launch(config_dir, dash_dir, logger, parallel=None, check_exists=True,
           args=None):
    "Launch the components required by the run configuration"
    if args is None:
        cluster_cfg = None
        config_name = None
        validate = None
        verbose = None
        dry_run = None
        event_check = None
        force_restart = None
    else:
        cluster_cfg = args.cluster_desc
        config_name = args.config_name
        validate = args.validate
        verbose = args.verbose
        dry_run = args.dry_run
        event_check = args.event_check
        force_restart = args.force_restart

    if config_name is None:
        config_name = livecmd_default_config()

    try:
        cluster_config = \
            DAQConfigParser.get_cluster_configuration(config_name,
                                                      use_active_config=False,
                                                      cluster_desc=cluster_cfg,
                                                      config_dir=config_dir,
                                                      validate=validate)
    except DAQConfigException:
        raise SystemExit("DAQ Config exception:\n\t%s" %
                         traceback.format_exc())

    if verbose:
        print("Version info: " + get_scmversion_str())
        if cluster_config.description is None:
            print("CLUSTER CONFIG: %s" % (cluster_config.config_name, ))
        else:
            print("CONFIG: %s" % (cluster_config.config_name, ))
            print("CLUSTER: %s" % cluster_config.description)

        print("NODES:")
        for node in sorted(cluster_config.nodes()):
            print("  %s(%s)" % (node.hostname, node.location), end=' ')

            for comp in sorted(node.components):
                print("%s#%d " % (comp.name, comp.id), end=' ')
            print()

    spade_dir = cluster_config.log_dir_for_spade
    copy_dir = cluster_config.log_dir_copies
    log_dir = cluster_config.daq_log_dir
    log_dir_fallback = os.path.join(PDAQ_HOME, "log")
    daq_data_dir = cluster_config.daq_data_dir

    do_cnc = True

    log_port = None
    live_port = DAQPort.I3LIVE_ZMQ

    ComponentManager.launch(do_cnc, dry_run, verbose, cluster_config, dash_dir,
                            config_dir, daq_data_dir, log_dir,
                            log_dir_fallback, spade_dir, copy_dir, log_port,
                            live_port, event_check=event_check,
                            check_exists=check_exists, start_missing=True,
                            force_restart=force_restart, logger=logger,
                            parallel=parallel)


def livecmd_default_config():
    "Get the default run configuration from LiveCmd"
    cmd = "livecmd config"

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, close_fds=True,
                            shell=True)
    proc.stdin.close()

    config = None
    for line in proc.stdout:
        if isinstance(line, bytes):
            line = line.decode()
        line = line.rstrip()

        if line.find("Traceback ") >= 0:
            raise SystemExit("Cannot get default run config file name from"
                             " \"livecmd\"")
        config = line
        break

    proc.stdout.close()
    proc.wait()

    if proc.returncode > 1:
        raise SystemExit("Cannot get default run config file name from"
                         " \"livecmd\"")

    return config


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()

    add_arguments_kill(parser)
    add_arguments_launch(parser)
    add_arguments_both(parser)
    add_arguments_old(parser)

    args = parser.parse_args()

    # complain about superfluous options
    check_arguments(args)

    if not args.nohostcheck:
        # exit if not running on expcont
        hostid = Machineid()
        if (not (hostid.is_control_host or
                 (hostid.is_unknown_host and hostid.is_unknown_cluster))):
            raise SystemExit("Are you sure you are launching"
                             " from the correct host?")

    if not args.force:
        check_detector_state()

    config_dir = find_pdaq_config()
    dash_dir = os.path.join(PDAQ_HOME, "dash")

    logger = ConsoleLogger()

    if not args.skipKill:
        kill(config_dir, logger, args=args)

    if not args.killOnly:
        launch(config_dir, dash_dir, logger, args=args)


if __name__ == "__main__":
    main()
