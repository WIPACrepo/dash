#!/usr/bin/env python

from RunJava import runJava

def add_arguments(parser):
    parser.add_argument(dest="fileList", nargs="+")

def dump_payloads(args):
    app = "icecube.daq.io.PayloadDumper"
    daqProjects = ["daq-common", "splicer", "payload", "daq-io"]
    mavenDeps = [("log4j", "log4j", "1.2.7"),
                 ("commons-logging", "commons-logging", "1.0.3")]

    runJava(app, ["-mx2000m"], args.fileList, daqProjects, mavenDeps)

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    dump_payloads(args)
