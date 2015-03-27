#!/usr/bin/env python

import os
import sys

from locate_pdaq import find_pdaq_config, find_pdaq_trunk

# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()


class FakeArgParser(object):
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
    # Command completion for "-C cluster"
    CMDTYPE_CONLY = "Conly"
    # Command completion for directory argument
    CMDTYPE_DONLY = "Donly"
    # Command completion for file argument
    CMDTYPE_FONLY = "Fonly"
    # Command completion for workspace argument
    CMDTYPE_WS = "WS"
    # Command doesn't require any completion
    CMDTYPE_NONE = "None"
    # Command completion is unknown
    CMDTYPE_UNKNOWN = "?"

    "Basic structure of a 'pdaq' command"
    @classmethod
    def add_arguments(cls, parser):
        "Argument handling for this subcommand"
        pass

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_UNKNOWN

    @classmethod
    def name(cls):
        "Name of this subcommand"
        raise NotImplementedError()

    @classmethod
    def run(cls, args):
        "Body of this subcommand"
        print "Not running '%s'" % cls.name()


class CmdDeploy(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DeployPDAQ import add_arguments
        add_arguments(parser, False)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CARG

    @classmethod
    def name(cls):
        return "deploy"

    @classmethod
    def run(cls, args):
        from DeployPDAQ import run_deploy
        run_deploy(args)


class CmdDumpData(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DumpPayloads import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_FONLY

    @classmethod
    def name(cls):
        return "dumpdata"

    @classmethod
    def run(cls, args):
        from DumpPayloads import dump_payloads
        dump_payloads(args)


class CmdFlash(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from RunFlashers import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CC

    @classmethod
    def name(cls):
        return "flash"

    @classmethod
    def run(cls, args):
        from RunFlashers import flash
        flash(args)


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
    def name(cls):
        return "kill"

    @classmethod
    def run(cls, args):
        from DAQLaunch import ConsoleLogger, check_detector_state, \
            check_running_on_expcont, kill

        if not args.nohostcheck:
            check_running_on_expcont("pdaq " + cls.name())

        if not args.force:
            check_detector_state()

        cfgDir = find_pdaq_config()
        logger = ConsoleLogger()

        args.clusterDesc = None

        kill(cfgDir, logger, args=args)


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
    def name(cls):
        return "launch"


    @classmethod
    def run(cls, args):
        from DAQLaunch import ConsoleLogger, check_detector_state, \
            check_running_on_expcont, kill, launch

        if not args.nohostcheck:
            check_running_on_expcont("pdaq " + cls.name())

        if not args.force:
            check_detector_state()

        cfgDir = find_pdaq_config()
        dashDir = os.path.join(PDAQ_HOME, "dash")

        logger = ConsoleLogger()

        if not args.skipKill:
            kill(cfgDir, logger, args=args)

        launch(cfgDir, dashDir, logger, args=args)

class CmdRun(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from ExpControlSkel import add_arguments
        add_arguments(parser, False)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CARG

    @classmethod
    def name(cls):
        return "run"

    @classmethod
    def run(cls, args):
        from ExpControlSkel import daqrun
        daqrun(args)


class CmdSortLogs(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from LogSorter import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_FONLY

    @classmethod
    def name(cls):
        return "sortlogs"

    @classmethod
    def run(cls, args):
        from LogSorter import sort_logs
        sort_logs(args)


class CmdStatus(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DAQStatus import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_NONE

    @classmethod
    def name(cls):
        return "status"

    @classmethod
    def run(cls, args):
        from DAQStatus import status
        status("pdaq " + cls.name(), args)


class CmdStopRun(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from DAQStopRun import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_NONE

    @classmethod
    def name(cls):
        return "stoprun"

    @classmethod
    def run(cls, args):
        from DAQStopRun import stoprun
        stoprun(args)


class CmdStdTest(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from StandardTests import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_CONLY

    @classmethod
    def name(cls):
        return "stdtest"

    @classmethod
    def run(cls, args):
        from StandardTests import run_tests
        run_tests(args)


class CmdTest(CmdStdTest):
    @classmethod
    def name(cls):
        return "test"


class CmdWorkspace(BaseCmd):
    @classmethod
    def add_arguments(cls, parser):
        from Workspace import add_arguments
        add_arguments(parser)

    @classmethod
    def cmdtype(cls):
        return cls.CMDTYPE_WS

    @classmethod
    def name(cls):
        return "workspace"

    @classmethod
    def run(cls, args):
        from Workspace import workspace
        workspace(args)


# map keywords to command classes
COMMANDS = [
    CmdDeploy,
    CmdDumpData,
    CmdFlash,
    CmdKill,
    CmdLaunch,
    CmdRun,
    CmdSortLogs,
    CmdStatus,
    CmdStdTest,
    CmdStopRun,
    CmdTest,
    CmdWorkspace,
]


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
        print cmdmap[args.cmdtype]
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
            print a
    else:
        for n in names:
            print n
