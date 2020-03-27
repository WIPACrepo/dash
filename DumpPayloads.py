#!/usr/bin/env python
#
# Dump all payloads in the data file

from RunJava import run_java


def add_arguments(parser):
    "Add command-line arguments"

    parser.add_argument("-D", "--config_dir", dest="config_dir",
                        help="Configuration directory")
    parser.add_argument("-S", "--summarize", dest="summarize",
                        action="store_true", default=False,
                        help=("Print time ranges and payload count" +
                              " for each file"))
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
    java_args = ["-mx2000m"]
    daq_projects = ["daq-common", "splicer", "payload", "daq-io"]
    maven_deps = [("log4j", "log4j", "1.2.7"), ]

    arglist = []
    if args.config_dir is not None:
        arglist += ["-D", args.config_dir]
    if args.summarize:
        arglist.append("-S")
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

    run_java(app, java_args, arglist, daq_projects, maven_deps)


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    dump_payloads(args)


if __name__ == "__main__":
    main()
