#!/usr/bin/env python
"""
`pdaq run` script which can be used to drive CnCServer when I3Live is
not available (e.g. pdaq2 split detector runs)
"""

# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006

from __future__ import print_function

import re
import sys
from BaseRun import FlasherScript
from cncrun import CnCRun
from utils.Machineid import Machineid

SVN_ID = "$Id: ExpControlSkel.py 17936 2021-05-27 20:50:40Z dglo $"


class DOMArgumentException(Exception):
    "Problem with a DOM argument"


class SubRunDOM(object):
    def __init__(self, *args):
        if len(args) == 7:
            self.string = args[0]
            self.pos = args[1]
            self.bright = args[2]
            self.window = args[3]
            self.delay = args[4]
            self.mask = args[5]
            self.rate = args[6]
            self.mbid = None
        elif len(args) == 6:
            self.string = None
            self.pos = None
            self.mbid = args[0]
            self.bright = args[1]
            self.window = args[2]
            self.delay = args[3]
            self.mask = args[4]
            self.rate = args[5]
        else:
            raise DOMArgumentException()

    @property
    def flasher_info(self):
        if self.mbid is not None:
            return (self.mbid, self.bright, self.window,
                    self.delay, self.mask, self.rate)

        if self.string is not None and self.pos is not None:
            return (self.string, self.pos, self.bright, self.window,
                    self.delay, self.mask, self.rate)

        raise DOMArgumentException()

    @property
    def flasher_hash(self):
        if self.mbid is not None:
            return {"MBID": self.mbid,
                    "brightness": self.bright,
                    "window": self.window,
                    "delay": self.delay,
                    "mask": str(self.mask),
                    "rate": self.rate}

        if self.string is not None and self.pos is not None:
            return {"stringHub": self.string,
                    "domPosition": self.pos,
                    "brightness": self.bright,
                    "window": self.window,
                    "delay": self.delay,
                    "mask": str(self.mask),
                    "rate": self.rate}

        raise DOMArgumentException()


class SubRun(object):
    FLASH = 1
    DELAY = 2

    def __init__(self, runtype, duration, runid):
        self.type = runtype
        self.duration = duration
        self.runid = runid
        self.domlist = []

    def __str__(self):
        if self.type == SubRun.DELAY:
            srtype = "DELAY"
        else:
            srtype = "FLASHER"

        sstr = "SubRun ID=%d TYPE=%s DURATION=%d\n" % (self.runid, srtype,
                                                       self.duration)
        if self.type == SubRun.FLASH:
            for dom in self.domlist:
                sstr += "%s\n" % str(dom)
        return sstr

    @property
    def flasher_info(self):
        if self.type != SubRun.FLASH:
            return None

        return [d.flasher_info for d in self.domlist]

    @property
    def flasher_dict_list(self):
        return [d.flasher_hash for d in self.domlist]


def add_arguments(parser, config_as_arg=False):
    "Add command-line arguments"

    parser.add_argument("-C", "--cluster-desc", dest="cluster_desc",
                        help="Cluster description name.")
    if config_as_arg:
        parser.add_argument("-c", "--config-name", dest="run_config",
                            required=True,
                            help="REQUIRED: Configuration name")
    else:
        parser.add_argument("-c", dest="minusC",
                            action="store_true", default=False,
                            help="Ignored, run config is a positional param")
        parser.add_argument("run_config",
                            help="Run configuration name")
    parser.add_argument("-d", "--duration-seconds", dest="duration",
                        default="8h",
                        help="Run duration (in seconds)")
    parser.add_argument("-f", "--flasher-script", dest="flasherScript",
                        help="Name of flasher script")
    parser.add_argument("-l", dest="duration",
                        default="8h",
                        help="Run duration (in seconds)")
    parser.add_argument("-n", "--num-runs", type=int, dest="num_runs",
                        default=10000000,
                        help="Number of runs")
    parser.add_argument("-r", "--remote-host", dest="remoteHost",
                        default="localhost",
                        help="Name of host on which CnCServer is running")
    parser.add_argument("-R", "--runsPerRestart", type=int,
                        dest="runsPerRestart",
                        default=1,
                        help="Number of runs per restart")
    parser.add_argument("-s", "--show_commands", dest="show_commands",
                        action="store_true", default=False,
                        help="Show the commands used to deploy and/or run")
    parser.add_argument("-x", "--show_command_output", dest="show_command_out",
                        action="store_true", default=False,
                        help=("Show the output of the deploy and/or"
                              " run commands"))
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help=("Disable checking the host type for"
                              " run permission"))


# adapted from live/misc/util.py
def get_duration_from_string(durstr):
    """
    Return duration in seconds based on string <durstr>

    >>> gdfs = get_duration_from_string
    >>> gdfs("1day")
    86400
    >>> gdfs("60mins")
    3600
    >>> gdfs("1day")
    86400
    >>> gdfs("5s")
    5
    >>> gdfs("13d")
    1123200
    >>> gdfs("123")
    Traceback (most recent call last):
    ValueError: String "123" is not a known duration format.  Try 30sec, 10min, 2days etc.
    """
    mtch = re.search(r"^(\d+)([smhd])(?:[eira][cny]?s?)?$", durstr)
    if mtch is None:
        raise ValueError("String \"%s\" is not a known duration format.  Try"
                         " 30sec, 10min, 2days etc." % (durstr, ))

    if mtch.group(2) == "s":
        scale = 1
    elif mtch.group(2) == "m":
        scale = 60
    elif mtch.group(2) == "h":
        scale = 60 * 60
    elif mtch.group(2) == "d":
        scale = 60 * 60 * 24
    else:
        raise ValueError("Unknown duration suffix \"%s\" in \"%s\"" %
                         (mtch.group(2), durstr))

    return int(mtch.group(1)) * scale


def daqrun(args):
    if args.run_config is None:
        raise SystemExit("You must specify a run configuration ( -c option )")

    if args.flasherScript is None:
        flasher_data = None
    else:
        flasher_data = FlasherScript.parse(args.flasherScript)

    cnc = CnCRun(show_commands=args.show_commands,
                 show_command_output=args.show_command_out)

    cluster_cfg = cnc.active_cluster_config()
    if cluster_cfg is None:
        raise SystemExit("Cannot determine cluster configuration")

    duration = get_duration_from_string(args.duration)

    num = 0
    while num < args.num_runs:
        run = cnc.create_run(None, args.run_config,
                             cluster_desc=args.cluster_desc,
                             flasher_data=flasher_data)
        run.start(duration, num_runs=args.runsPerRestart)

        try:
            try:
                run.wait()
            except KeyboardInterrupt:
                print("Run interrupted by user")
                break
        finally:
            print("Stopping run...", file=sys.stderr)
            run.finish()

        num += args.runsPerRestart


def main():
    "Main program"
    import argparse

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    if not args.nohostcheck:
        hostid = Machineid()
        if not (hostid.is_control_host or
                (hostid.is_unknown_host and hostid.is_unknown_cluster)):
            # you should either be a control host or a totally unknown host
            raise SystemExit("Are you sure you are running ExpControlSkel "
                             "on the correct host?")

    daqrun(args)


if __name__ == "__main__":
    main()
