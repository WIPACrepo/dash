#!/usr/bin/env python
#
# Dump all payloads in the data file

from RunJava import runJava


def add_arguments(parser):
    parser.add_argument("-D", "--config_dir", dest="config_dir",
                        help="Configuration directory")
    parser.add_argument("-f", "--fullDump", dest="fullDump",
                        action="store_true", default=False,
                        help="Dump entire payload")
    parser.add_argument("-H", "--hexDump", dest="hexDump",
                        action="store_true", default=False,
                        help="Dump payload bytes as hexadecimal blocks")
    parser.add_argument("-n", "--numToDump", type=int, dest="numToDump",
                        default=None,
                        help="Maximum number of payloads to dump")
    parser.add_argument("-r", "--config_name", dest="config_name",
                        help="Run configuration name")
    parser.add_argument(dest="fileList", nargs="+")


def dump_payloads(args):
    app = "icecube.daq.io.PayloadDumper"
    javaArgs = ["-mx2000m"]
    daqProjects = ["daq-common", "splicer", "payload", "daq-io"]
    mavenDeps = [("log4j", "log4j", "1.2.7"),
                 ("commons-logging", "commons-logging", "1.0.3")]

    arglist = []
    if args.config_dir is not None:
        arglist += ["-D", args.config_dir]
    if args.fullDump:
        arglist.append("-f")
    if args.hexDump:
        # note that the Java argument is lowercase 'h', not 'H'
        arglist.append("-h")
    if args.numToDump is not None:
        arglist += ["-n", str(args.numToDump)]
    if args.config_name is not None:
        arglist += ["-r", args.config_name]

    arglist += args.fileList

    runJava(app, javaArgs, arglist, daqProjects, mavenDeps)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    dump_payloads(args)
