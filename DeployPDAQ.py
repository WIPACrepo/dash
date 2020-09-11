#!/usr/bin/env python

# DeployPDAQ.py
# Jacobsen Feb. 2007
#
# Deploy valid pDAQ cluster configurations to any cluster

from __future__ import print_function

import os
import subprocess
import sys
import threading
import time
import traceback

from DAQConfigExceptions import DAQConfigException
from DAQConfig import DAQConfig, DAQConfigParser
from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from scmversion import store_scmversion
from utils.Machineid import Machineid
from xmlparser import XMLBadFileError

# pdaq subdirectories to be deployed
SUBDIRS = ("target", "dash", "schema", "src", "PyDOM")

# Defaults for a few args
NICE_LEVEL_DEFAULT = 19
EXPRESS_DEFAULT = False
WAIT_SECONDS_DEFAULT = 2

# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()


def add_arguments(parser, config_as_arg=True):
    "Add command-line arguments"

    parser.add_argument("-C", "--cluster-desc", dest="cluster_desc",
                        help="Cluster description name")
    if config_as_arg:
        parser.add_argument("-c", "--config-name", dest="config_name",
                            required=True,
                            help="REQUIRED: Configuration name")
    else:
        parser.add_argument("config_name",
                            help="Run configuration name")
    parser.add_argument("--delete", dest="delete",
                        action="store_true", default=True,
                        help="Run rsync's with --delete")
    parser.add_argument("--no-delete", dest="delete",
                        action="store_false", default=True,
                        help="Run rsync's without --delete")
    parser.add_argument("-l", "--list-configs", dest="print_list",
                        action="store_true", default=False,
                        help="List available configs")
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help=("Don't run rsyncs, just print as they would"
                              " be run (disables quiet)"))
    parser.add_argument("--deep-dry-run", dest="deep_dry_run",
                        action="store_true", default=False,
                        help=("Run rsync's with --dry-run"
                              " (implies verbose and serial)"))
    parser.add_argument("-q", "--quiet", dest="verbose",
                        action="store_false", default=None,
                        help="Run quietly")
    parser.add_argument("-t", "--timeout", type=int, dest="timeout",
                        default=WAIT_SECONDS_DEFAULT,
                        help=("Number of seconds to wait between"
                              " status messages"))
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=None,
                        help="Be chatty")
    parser.add_argument("--nice", type=int, dest="nice_level",
                        default=NICE_LEVEL_DEFAULT,
                        help=("Set nice adjustment for remote rsyncs"
                              " [default=%s]" % NICE_LEVEL_DEFAULT))
    parser.add_argument("-E", "--express", dest="express",
                        action="store_true", default=EXPRESS_DEFAULT,
                        help=("Express rsyncs, unsets and overrides any/all"
                              " nice adjustments"))
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help=("Disable checking the host type"
                              " for run permission"))
    parser.add_argument("-z", "--no-schema-validation", dest="validation",
                        action="store_false", default=True,
                        help=("Disable schema validation of xml"
                              " configuration files"))


class RSyncRunner(object):
    """
    Build a list of rsync commands, then run them all in parallel
    """

    # default number of threads used to run all commands
    DEFAULT_THREADS = 16

    def __init__(self):
        self.__queue = []
        self.__qlock = threading.Lock()

        self.__running = False
        self.__threads = None
        self.__joined_threads = 0

    @classmethod
    def __clean_string(cls, string):
        """
        Trim trailing whitespace and convert empty lines to None
        """
        if string is not None:
            string = string.rstrip()
            if string == "":
                string = None
        return string

    @classmethod
    def __clean_rsync_errors(cls, string):
        """
        Get rid of excess error lines from rsync
        Return the remaining lines as an array of strings
        """
        if string is None:
            return None

        kept = []
        for line in string.split(os.linesep):
            if line.find("connection unexpectedly closed") >= 0:
                continue
            if line.find("unexplained error") >= 0 and \
              len(kept) > 0:  # pylint: disable=len-as-condition
                continue
            kept.append(line)
        return kept

    def __run(self):
        """
        Main thread loop
        """
        self.__running = True
        while self.__running:
            with self.__qlock:
                # if no commands remain, this thread can exit
                if len(self.__queue) == 0:  # pylint: disable=len-as-condition
                    break

                # queue contains a simple description and full shell command
                description, cmdhost, cmd = self.__queue.pop()

            # spawn a subprocess, read back the output and/or errors
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            outline, errline = proc.communicate()

            # clean up returned strings
            outline = self.__clean_string(outline)
            errlines = self.__clean_rsync_errors(self.__clean_string(errline))

            if proc.returncode == 0:
                # there shouldn't be any error messages if return code is 0
                if errlines is not None:
                    with self.__qlock:
                        print("Unexpected error(s) after rsyncing %s to %s" %
                              (description, cmdhost))
                        for line in errlines:
                            print("\t%s" % (line, ), file=sys.stderr)
            else:
                # attempt to make the error lines readable
                with self.__qlock:
                    if errlines is None or len(errlines) > 1:
                        errstr = ""
                    else:
                        errstr = "\n\t" + errlines[0]
                        errlines = None

                    print("rsyncing %s to %s failed with return code %d%s" %
                          (description, cmdhost, proc.returncode, errstr),
                          file=sys.stderr)
                    if outline is not None:
                        print("%s:%s>> %s" % (cmdhost, description, outline))
                    if errlines is not None:
                        for line in errlines:
                            print("\t%s" % (line, ), file=sys.stderr)

    def add_first(self, description, host, command):
        """
        Add this command to the front of the queue
        """
        with self.__qlock:
            self.__queue.insert(0, (description, host, command))

    def add_last(self, description, host, command):
        """
        Append this command to the back of the queue
        """
        with self.__qlock:
            self.__queue.append((description, host, command))

    @property
    def num_remaining_commands(self):
        "Return the number of commands which have not yet been run"
        return len(self.__queue)

    @property
    def running_threads(self):
        "Return the number of running threads"
        if self.__threads is None:
            raise Exception("Threads have not been started")
        return len(self.__threads) - self.__joined_threads

    def start(self, num_threads=None):
        """
        Launch all the threads and wait until they've finished
        """
        if self.__threads is not None:
            raise Exception("Threads can only be started once")

        # if unspecified, use the default number of threads
        if num_threads is None:
            num_threads = self.DEFAULT_THREADS
        else:
            num_threads = int(num_threads)

        # initialize thread-tracking stuff
        self.__threads = []
        self.__joined_threads = 0

        # start all threads
        for idx in range(num_threads):
            thrd = threading.Thread(name="Pool#%d" % idx, target=self.__run)
            thrd.start()

            self.__threads.append(thrd)

        # wait for threads to finish
        while self.__joined_threads < len(self.__threads):
            for idx, thrd in enumerate(self.__threads):
                if thrd is not None:
                    thrd.join(0.1)
                    if not thrd.is_alive():
                        self.__threads[idx] = None
                        self.__joined_threads += 1

    @property
    def total_threads(self):
        "Return the number of threads created by start()"
        return len(self.__threads)


def collapse_user(path, home=None):
    """
    If the path starts with this user's home directory, replace it with
    '~user' (because ~pdaq may be a different directory on remote machines)
    """
    if path.startswith(home):
        subdir = path[len(home):]
        if subdir.startswith(os.sep):
            return "~" + os.environ["USER"] + subdir
    return path


def deploy(config, pdaq_dir, subdirs, delete, dry_run, deep_dry_run,
           trace_level, nice_level=NICE_LEVEL_DEFAULT, express=EXPRESS_DEFAULT,
           wait_seconds=WAIT_SECONDS_DEFAULT, home=None,
           rsync_runner=None):
    """
    Deploy pDAQ software and configuration files to the cluster
    """
    if subdirs is None:
        subdirs = SUBDIRS

    if home is None:
        home = os.environ["HOME"]

    # convert to a relative path
    # (~pdaq is a different directory on different machines)
    pdaq_dir = collapse_user(pdaq_dir, home=home)

    # record the release/revision info
    if not dry_run:
        store_scmversion(pdaq_dir)

    # record the configuration being deployed so
    # it gets copied along with everything else
    if not dry_run:
        config.write_cache_file()

    # if user or unit tests didn't specify a command runner, create one
    if rsync_runner is None:
        rsync_runner = RSyncRunner()

    # build stub of rsync command
    if express:
        rsync_cmd_stub = "rsync"
    else:
        rsync_cmd_stub = 'nice rsync --rsync-path "nice -n %d rsync"' % \
          (nice_level, )

    rsync_cmd_stub += " -azLC%s%s" % (delete and ' --delete' or '',
                                      deep_dry_run and ' --dry-run' or '')
    rsync_cmd_stub += " --exclude .hg"

    # set 'rsync_config_src' to the configuration directory path, or None
    # if 'config' is a subdirectory of 'pdaq'
    # (pDAQ originally kept configuration files in a 'config' subdirectory of
    #  the 'pdaq' metaproject, but stopped because the config directory was
    #  tied to the release)
    config_dir = find_pdaq_config()
    config_subdir = os.path.join(os.path.expanduser(pdaq_dir), "config")
    if config_dir == config_subdir:
        rsync_config_src = None
    else:
        rsync_config_src = config_dir

    # The 'SRC' arg for the main rsync command.  The sh "{}" syntax is used
    # here so that only one rsync is required for each node. (Running
    # multiple rsync's in parallel appeared to give rise to race
    # conditions and errors.)
    rsync_deploy_src = os.path.join(pdaq_dir, "{" + ",".join(subdirs) + "}")
    if not rsync_deploy_src.startswith("~"):
        rsync_deploy_src = os.path.abspath(rsync_deploy_src)

    # Check if target directory (the result of a build) is present
    target_dir = os.path.join(pdaq_dir, 'target')
    if target_dir.startswith("~"):
        target_dir = os.path.join(home, target_dir[target_dir.find("/") + 1:])
    if not os.path.isdir(target_dir) and not dry_run:
        raise Exception(("Target dir (%s) does not exist.\n" % target_dir) +
                        "Did you run 'mvn clean install assembly:assembly'?")

    # get list of unique hosts (there's probably a much better way to do this)
    hosts = {}
    for node in config.nodes():
        hosts[node.hostname] = 1

    if len(hosts) > 0 and trace_level > 0:  # pylint: disable=len-as-condition
        print("COMMANDS:")

    for node_name in sorted(hosts.keys()):
        # Ignore localhost - already "deployed"
        if node_name == "localhost":
            continue

        # build the command to rsync the executables
        cmd = "%s %s %s:%s" % \
          (rsync_cmd_stub, rsync_deploy_src, node_name, pdaq_dir)
        if trace_level > 0 or dry_run:
            print("  " + cmd)

        # add to the end of the command queue
        if not dry_run:
            rsync_runner.add_last("application", node_name, cmd)

        if rsync_config_src is not None:
            # build the command to rsync the configuration directory
            cmd = "%s %s %s:~%s" % (rsync_cmd_stub, rsync_config_src,
                                    node_name, os.environ["USER"])
            if trace_level > 0 or dry_run:
                print("  " + cmd)

            # add to the front of the command queue
            if not dry_run:
                rsync_runner.add_first("configuration", node_name, cmd)

    if not dry_run:
        # start the threads and wait until all are finished
        rsync_runner.start()
        while True:
            num = rsync_runner.running_threads
            if num is not None:
                if num == 0:
                    break
                if trace_level >= 0:
                    print("Waiting for %d (of %d) threads"
                          " (%d commands remaining)" %
                          (num, rsync_runner.total_threads,
                           rsync_runner.num_remaining_commands))
            time.sleep(wait_seconds)


def hub_type(comp_id):
    "Return a description of the hub type"
    if comp_id % 1000 == 0:
        return "amanda"
    if comp_id % 1000 >= 200:
        return "icetop"
    return "in-ice"


def run_deploy(args):
    "Work through all the options and call the deploy() function"

    # A deep-dry-run implies verbose
    if args.deep_dry_run:
        args.verbose = True

    # Map quiet/verbose to a 3-value tracelevel
    trace_level = 1
    if args.verbose is None:
        trace_level = 0
    elif not args.verbose:
        trace_level = -1

    # How often to report count of processes waiting to finish
    wait_seconds = None
    if trace_level >= 0 and args.timeout > 0:
        wait_seconds = max(args.timeout * 0.01, 2)

    if args.print_list:
        DAQConfig.print_config_file_list()
        raise SystemExit

    if not args.config_name:
        print('No configuration specified', file=sys.stderr)
        raise SystemExit

    try:
        cdesc = args.cluster_desc
        config = \
            DAQConfigParser.get_cluster_configuration(args.config_name,
                                                      cluster_desc=cdesc,
                                                      validate=args.validation)
    except XMLBadFileError:
        print('Configuration "%s" not found' % args.config_name,
              file=sys.stderr)
        raise SystemExit
    except DAQConfigException:
        print('Problem with configuration \"%s\"' %
              (args.config_name, ), file=sys.stderr)
        traceback.print_exc()
        raise SystemExit

    if trace_level >= 0:
        if config.description is None:
            print("CLUSTER CONFIG: %s" % config.config_name)
        else:
            print("CONFIG: %s" % config.config_name)
            print("CLUSTER: %s" % config.description)

        print("NODES:")
        for node in sorted(config.nodes()):
            if node.hostname == node.location:
                print("  %s" % node.hostname)
            else:
                print("  %s(%s)" % (node.hostname, node.location), end=' ')

            for comp in sorted(node.components):
                print(comp.fullname, end=' ')
                if comp.is_hub:
                    print("[%s]" % hub_type(comp.id), end=' ')
                print(" ", end=' ')
            print()

    deploy(config, PDAQ_HOME, SUBDIRS, args.delete,
           args.dry_run, args.deep_dry_run, trace_level,
           wait_seconds=wait_seconds, nice_level=args.nice_level,
           express=args.express)


def main():
    "Main program"
    parser = argparse.ArgumentParser()

    add_arguments(parser)

    args = parser.parse_args()

    if not args.nohostcheck:
        # exit the program if it's not running on 'access' on SPS/SPTS
        hostid = Machineid()
        if not (hostid.is_build_host or
                (hostid.is_unknown_host and hostid.is_unknown_cluster)):
            raise SystemExit("Are you sure you are deploying"
                             " from the correct host?")

    run_deploy(args)


if __name__ == "__main__":
    import argparse

    main()
