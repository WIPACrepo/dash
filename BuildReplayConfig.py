#!/usr/bin/env python
#
# Build a "replay" run configuration from a directory full of hitspool
# files.  The top-level directory should contain a set of subdirectories
# whose names include "ichub##" and/or "ithub##", and those subdirectories
# should hold the actual HitSpool files.  An example might be:
#
#    /net/data2/pdaq/testdaq/hitspool/from_sndaq_alerts/2013/0403/
#        SNALERT_20130403_0611113_sps-ichub01.sps.icecube.southpole.usap.gov
#            HitSpool-1229.dat
#            HitSpool-1230.dat
#        ...
#        ithub11
#            HitSpool-11.dat
#            HitSpool-12.dat

import fnmatch
import os
import re
import sys


HUB_PAT = re.compile(r"i([ct])hub(\d+)")


def process(path, ext, basename, trigcfg):
    hubdirs = {}

    for root, _, files in os.walk(path):
        found = False
        for _ in fnmatch.filter(files, "*" + ext):
            found = True
            break

        if not found:
            continue

        hspath = os.path.dirname(root)
        hsname = os.path.basename(root)

        if hspath not in hubdirs:
            hubdirs[hspath] = {}
        hubdirs[hspath][hsname] = 1

    dkeys = hubdirs.keys()
    dkeys.sort()

    for hd in dkeys:
        name = "%s-%s.xml" % (basename, hd.replace("/", "-"))
        if path == hd:
            rcbase = hd
        else:
            rcbase = os.path.join(path, hd)
        with open(name, "w") as out:
            writeRunConfig(out, rcbase, trigcfg, hubdirs[hd].keys())


def writeRunConfig(out, basedir, trigcfg, hubs):
    sawInice = False
    sawIcetop = False

    fullpath = os.path.abspath(basedir)

    finalhubs = []
    for hub in sorted(hubs):
        m = HUB_PAT.match(hub)
        if m is None:
            print >>sys.stderr, "Ignoring unrecognized directory \"%s\"" % hub
            continue

        hubtype = m.group(1)
        hubnum = int(m.group(2))

        if hubtype == "t":
            hubnum = hubnum + 200
            sawIcetop = True
        elif hubtype == "c":
            sawInice = True
        else:
            print >>sys.stderr, "Hub \"%s\" is neither in-ice nor icetop" % hub
            continue

        finalhubs.append((hub, hubnum))

    if not sawInice and not sawIcetop:
        print >>sys.stderr, "No in-ice or icetop hubs found!"
        return

    print >>out, '<?xml version="1.0" encoding="UTF-8"?>'
    print >>out, '<runConfig>'

    # wait a long time before killing the run
    print >>out, '    <watchdog period="60"/>'
    print >>out, '    <updateHitSpoolTimes disabled="true"/>'

    print >>out, '    <replayFiles baseDir="%s">' % fullpath
    for (hubname, hubnum) in finalhubs:
        print >>out, '        <hits hub="%d" source="%s"/>' % (hubnum, hubname)
    print >>out, '    </replayFiles>'

    print >>out, '    <triggerConfig>%s</triggerConfig>' % trigcfg
    if sawInice:
        print >>out, '    <runComponent name="inIceTrigger"/>'
    if sawIcetop:
        print >>out, '    <runComponent name="iceTopTrigger"/>'
    print >>out, '    <runComponent name="globalTrigger"/>'
    print >>out, '    <runComponent name="eventBuilder"/>'
    print >>out, '</runConfig>'


if __name__ == "__main__":
    import argparse

    op = argparse.ArgumentParser()
    op.add_argument("-b", "--basename", dest="basename",
                    default="replay",
                    help="Run configuration base file name")
    op.add_argument("-t", "--trigger", dest="trigcfg",
                    default="sps-2013-no-physminbias-001",
                    help="Trigger configuration file name")
    op.add_argument("-x", "--extension", dest="ext",
                    default=".dat",
                    help="Hitspool file extension (defaults to \".dat\")")
    op.add_argument("directory", nargs="*")

    args = op.parse_args()

    if args.ext.startswith("."):
        ext = args.ext
    else:
        ext = "." + args.ext

    for path in args.directory:
        process(path, ext, args.basename, args.trigcfg)
