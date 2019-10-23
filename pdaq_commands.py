#!/usr/bin/env python

from __future__ import print_function

import os

from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from utils.Machineid import Machineid

# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()

# list of all pDAQ command objects (classes which add the @command decorator)
COMMANDS = []

def command(cls):
    """
    Decorator which adds a command class to the master list
    """
    COMMANDS.append(cls)
    return cls


class FakeArgParser(object):
    """
    This is passed to commands' add_arguments() lists to build the list of
    valid arguments for bash
    """
    def __init__(self):
        self.__args = []

    def add_argument(self, *args, **kwargs):
        for a in args:
            if len(a) > 0 and a[0] == "-":
                self.__args.append(a)

    def get_arguments(self):
        return self.__args


class BaseCmd(object):
    # Command completion for "-C cluster" and a runconfig argument
    CMDTYPE_CARG = "Carg"
    # Command completion for "-C cluster" and "-c runconfig"
    CMDTYPE_CC = "Cc"
    # Command completion for "help <cmd>"
    CMDTYPE_CMD = "Cmd"
    # Command completion for "-C cluster"
    CMDTYPE_CONLY = "Conly"
    # Command completion for directory argument
    CMDTYPE_DONLY = "Donly"
    # Command completion for file argument
    CMDTYPE_FONLY = "Fonly"
    # Command completion for log directory argument
    CMDTYPE_LD = "LD"
    # Command completion for workspace argument
    CMDTYPE_WS = "WS"
    # Command doesn't require any completion
    CMDTYPE_NONE = "None"
    # Command completion is unknown
    CMDTYPE_UNKNOWN = "?"

    # list of commands
    COMMANDS = []

    "Basic structure of a 'pdaq' command"
    @classmethod
    def add_arguments(cls, parser):
        """
        Argument handling for this subcommand
        NOTE: if the command is locked to a specific host type but the user may
        want to run it elsewhere, add an option to set 'nohostcheck' to True
        """
        pass

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_UNKNOWN

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        raise NotImplementedError()

    @classmethod
    def epilog(cls):
        "Optional extra information/instructions for a subcommand"
        return None

    @classmethod
    def is_valid_host(cls, args):
        "Is this command allowed to run on this machine?"
        raise NotImplementedError()

    @classmethod
    def name(cls):
        "Name of this subcommand"
        raise NotImplementedError()

    @classmethod
    def run(cls, args):
        "Body of this subcommand"
        print("Not running '%s'" % cls.name())


@command
class CmdDeploy(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DeployPDAQ import add_arguments
        add_arguments(parser, False)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CARG

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Deploy pDAQ software and associated files to the cluster"

    @classmethod
    def is_valid_host(cls, args):
        "Deployment is done from the build host"
        return Machineid.is_host(Machineid.BUILD_HOST)

    @classmethod
    def name(cls):
        return "deploy"

    @classmethod
    def run(cls, args):
        from DeployPDAQ import run_deploy
        run_deploy(args)


@command
class CmdDumpData(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DumpPayloads import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_FONLY

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Dump a pDAQ data file (hitspool, physics, moni, sn, etc.)"

    @classmethod
    def is_valid_host(cls, args):
        "Any host can dump data"
        return True

    @classmethod
    def name(cls):
        return "dumpdata"

    @classmethod
    def run(cls, args):
        from DumpPayloads import dump_payloads
        dump_payloads(args)


@command
class CmdDumpHSDB(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DumpHitspoolDB import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_FONLY

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Dump the hitspool database list of hit files and contents"

    @classmethod
    def is_valid_host(cls, args):
        "Any host can dump a hitspool DB"
        return True

    @classmethod
    def name(cls):
        return "dumphsdb"

    @classmethod
    def run(cls, args):
        from DumpHitspoolDB import dump_db
        dump_db(args)


@command
class CmdFlash(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from RunFlashers import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CC

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Control a flasher run"

    @classmethod
    def is_valid_host(cls, args):
        "Flashers are run on the control host"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "flash"

    @classmethod
    def run(cls, args):
        from RunFlashers import flash
        flash(args)


@command
class CmdHelp(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("helpcmd", help="Command name")

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CMD

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Print the help message for a command"

    @classmethod
    def is_valid_host(cls, args):
        "Any host can get help"
        return True

    @classmethod
    def name(cls):
        return "help"

    @classmethod
    def run(cls, args):
        for cmd in COMMANDS:
            if cmd.name() == args.helpcmd:
                import argparse
                import sys

                # load an argparse object with this command's arguments
                base = os.path.basename(sys.argv[0])
                p = argparse.ArgumentParser(prog="%s %s" % (base, cmd.name()))
                try:
                    cmd.add_arguments(p)
                except:
                    pass

                # print command name and description
                print("%s - %s" % (cmd.name(), cmd.description()))
                print()

                # let argparse deal with the rest of the help message
                p.print_help()

                return

        print("Unknown command '%s'" % args.helpcmd)


@command
class CmdKill(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DAQLaunch import add_arguments_both, add_arguments_kill
        add_arguments_both(parser)
        add_arguments_kill(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_NONE

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Kill the pDAQ components running on the cluster"

    @classmethod
    def is_valid_host(cls, args):
        "Only a control host can kill components"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "kill"

    @classmethod
    def run(cls, args):
        from DAQLaunch import ConsoleLogger, check_detector_state, kill

        if not args.force:
            check_detector_state()

        cfgDir = find_pdaq_config()
        logger = ConsoleLogger()

        args.clusterDesc = None

        kill(cfgDir, logger, args=args)


@command
class CmdLaunch(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DAQLaunch import add_arguments_both, add_arguments_launch
        add_arguments_both(parser)
        add_arguments_launch(parser, False)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CARG

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Start pDAQ components on the cluster"

    @classmethod
    def is_valid_host(cls, args):
        "Only a control host can launch components"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "launch"

    @classmethod
    def run(cls, args):
        from DAQLaunch import ConsoleLogger, check_detector_state, kill, launch

        if not args.force:
            check_detector_state()

        cfgDir = find_pdaq_config()
        dashDir = os.path.join(PDAQ_HOME, "dash")

        logger = ConsoleLogger()

        if not args.skipKill:
            kill(cfgDir, logger, args=args)

        launch(cfgDir, dashDir, logger, args=args)


@command
class CmdQueueLogs(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from SpadeQueue import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_LD

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Submit pDAQ log files to SPADE for transmission to the North"

    @classmethod
    def is_valid_host(cls, args):
        "Any host can have log files"
        return True

    @classmethod
    def name(cls):
        return "queuelogs"

    @classmethod
    def run(cls, args):
        from SpadeQueue import queue_logs
        queue_logs(args)


@command
class CmdRemoveHubs(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from RemoveHubs import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CARG

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Remove hubs or racks from a run configuration"

    @classmethod
    def is_valid_host(cls, args):
        "Any host can have log files"
        return Machineid.is_host(Machineid.BUILD_HOST)

    @classmethod
    def name(cls):
        return "removehubs"

    @classmethod
    def run(cls, args):
        from RemoveHubs import remove_hubs
        remove_hubs(args)


@command
class CmdRun(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from ExpControlSkel import add_arguments
        add_arguments(parser, False)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CARG

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Start a pDAQ run (does not communicate with Live)"

    @classmethod
    def is_valid_host(cls, args):
        "Only a control host can start runs"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "run"

    @classmethod
    def run(cls, args):
        from ExpControlSkel import daqrun
        daqrun(args)


@command
class CmdRunNumber(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from RunNumber import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_NONE

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Get/set last run number"

    @classmethod
    def is_valid_host(cls, args):
        "Only a control host can get/set run numbers"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "runnumber"

    @classmethod
    def run(cls, args):
        from RunNumber import get_or_set_run_number
        get_or_set_run_number(args)


@command
class CmdSortLogs(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from LogSorter import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_LD

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Combine all log entries from a run"

    @classmethod
    def is_valid_host(cls, args):
        "Any host can have log files"
        return True

    @classmethod
    def name(cls):
        return "sortlogs"

    @classmethod
    def run(cls, args):
        from LogSorter import sort_logs
        sort_logs(args)


@command
class CmdStatus(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DAQStatus import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_NONE

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Print the status of all active pDAQ components"

    @classmethod
    def is_valid_host(cls, args):
        "Only a control host can check component status"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "status"

    @classmethod
    def run(cls, args):
        from DAQStatus import print_status
        print_status(args)


@command
class CmdStopRun(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DAQStopRun import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_NONE

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Stop the current pDAQ run (does not communicate with Live)"

    @classmethod
    def is_valid_host(cls, args):
        "Only a control host can emergency-stop runs"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "stoprun"

    @classmethod
    def run(cls, args):
        from DAQStopRun import stoprun
        stoprun(args)


@command
class CmdStdTest(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from StandardTests import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CONLY

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Run the standard pDAQ test configurations to" \
            " validate the system"

    @classmethod
    def is_valid_host(cls, args):
        """
        Run `pdaq deploy` on build host, run StandardTests on control host
        """
        bits = Machineid.BUILD_HOST | Machineid.CONTROL_HOST
        return Machineid.is_host(bits)

    @classmethod
    def name(cls):
        return "stdtest"

    @classmethod
    def run(cls, args):
        from StandardTests import run_tests
        run_tests(args)


@command
class CmdSummarize(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from Summarize import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_FONLY

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Summarize DAQ runs"

    @classmethod
    def is_valid_host(cls, args):
        "This can be run wherever there are 'daqrunXXXXXX' directories"
        return True

    @classmethod
    def name(cls):
        return "summarize"

    @classmethod
    def run(cls, args):
        from Summarize import summarize
        summarize(args)


@command
class CmdTail(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from TailLive import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_NONE

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Add colors to Live's log output"

    @classmethod
    def epilog(cls):
        return "Color choices can be customized in either $HOME/.pdaq_colors" \
            " or in a file pointed to by the PDAQ_COLORS environment" \
            " variable.  Use --print_colors to dump the current choices."

    @classmethod
    def is_valid_host(cls, args):
        "Only makes sense on expcont"
        return Machineid.is_host(Machineid.CONTROL_HOST)

    @classmethod
    def name(cls):
        return "taillive"

    @classmethod
    def run(cls, args):
        from TailLive import tail_logs
        tail_logs(args)


@command
class CmdTest(CmdStdTest):
    @classmethod
    def name(cls):
        return "test"


@command
class CmdWorkspace(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from Workspace import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_WS

    @classmethod
    def description(cls):
        "One-line description of this subcommand"
        return "Print or change the symlink to the current pDAQ workspace"

    @classmethod
    def is_valid_host(cls, args):
        "Workspaces only exist on build host"
        return Machineid.is_host(Machineid.BUILD_HOST)

    @classmethod
    def name(cls):
        return "workspace"

    @classmethod
    def run(cls, args):
        from Workspace import workspace
        workspace(args)


if __name__ == "__main__":
    import argparse

    cmdmap = {}
    names = []
    for v in COMMANDS:
        cmdmap[v.name()] = v.cmdtype()
        names.append(v.name())

    p = argparse.ArgumentParser()
    p.add_argument("-a", dest="arglist", choices=names,
                   help="Print list of arguments for a command")
    p.add_argument("-n", dest="shownames",
                   action="store_true", default=False,
                   help="Print list of all valid command names")
    p.add_argument("-t", dest="cmdtype", choices=names,
                   help="Print command type")
    args = p.parse_args()

    if args.cmdtype is not None:
        print(cmdmap[args.cmdtype])
    elif args.arglist is not None:
        fakeargs = FakeArgParser()
        for v in COMMANDS:
            if v.name() != args.arglist:
                continue

            try:
                v.add_arguments(fakeargs)
            except:
                pass
        for a in fakeargs.get_arguments():
            print(a)
    else:
        for n in names:
            print(n)
