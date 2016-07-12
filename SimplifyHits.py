#!/usr/bin/env python
#
# Reduce hits from a file or HitSpool directory to only the SimpleHits
# which would be sent to the local triggers

from RunJava import runJava

def add_arguments(parser):
    parser.add_argument("-H", "--hubNumber", type=int, dest="hubNumber",
                        default=None, help="Hub number")
    parser.add_argument("-n", "--numToDump", type=int, dest="numToDump",
                        default=None,
                        help="Maximum number of payloads to dump")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print more details")
    parser.add_argument(dest="fileList", nargs="+")

def simplify_hits(args):
    app = "icecube.daq.io.HitSimplifier"
    daqProjects = ["daq-common", "splicer", "payload", "daq-io"]
    mavenDeps = [("log4j", "log4j", "1.2.7"),
                 ("commons-logging", "commons-logging", "1.0.3")]

    arglist = []
    if args.verbose:
        arglist.append("-v")
    if args.hubNumber is not None:
        arglist += ["-h", str(args.hubNumber)]
    if args.numToDump is not None:
        arglist += ["-n", str(args.numToDump)]

    arglist += args.fileList

    runJava(app, ["-mx2000m"], arglist, daqProjects, mavenDeps)

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    simplify_hits(args)
