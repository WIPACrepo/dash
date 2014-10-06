#!/usr/bin/env python

import socket
import sys

from DAQConst import DAQPort
from DAQRPC import RPCClient
from RunSetDebug import RunSetDebug


def parseFlags(flagStr):
    bits = 0
    error = False

    for f in flagStr.split(","):
        fl = f.lower()
        if fl == "none":
            continue

        found = False
        for (k, v) in RunSetDebug.NAME_MAP.iteritems():
            if k.lower() == fl:
                bits |= v
                found = True
                break
        if not found:
            print >>sys.stderr, "Unknown debugging flag \"%s\"" % f
            error = True

    if error:
        raise SystemExit

    return bits

if __name__ == "__main__":
    import argparse

    op = argparse.ArgumentParser()
    op.add_argument("-d", "--debugFlags", dest="debugFlags",
                    help="Debug flags")
    op.add_argument("-l", "--list", dest="listActive",
                    action="store_true", default=False,
                    help="List active runset IDs")
    op.add_argument("-L", "--list-flags", dest="listFlags",
                    action="store_true", default=False,
                    help="List debugging flags")
    op.add_argument("runset", nargs="*")

    args = op.parse_args()

    rpc = RPCClient("localhost", DAQPort.CNCSERVER)

    if args.listActive:
        try:
            idList = rpc.rpc_runset_list_ids()
            print "Run set IDs:"
            for i in idList:
                print "  %d" % i
        except socket.error:
            print >> sys.stderr, "Cannot connect to CnCServer"

    if args.listFlags:
        keys = RunSetDebug.NAME_MAP.keys()
        keys.sort()
        print "Debugging flags:"
        for k in keys:
            print "  " + k

    if args.listActive or args.listFlags:
        raise SystemExit

    if args.debugFlags is None:
        bits = RunSetDebug.ALL
    else:
        bits = parseFlags(args.debugFlags)

    debugBits = None
    for a in args.runset:
        try:
            rsid = int(a)
        except ValueError:
            print >> sys.stderr, "Ignoring bad ID \"%s\"" % a
            continue

        try:
            print "Runset#%d -> 0x%0x" % (rsid, bits)
            debugBits = rpc.rpc_runset_debug(rsid, bits)
        except socket.error:
            print >> sys.stderr, "Cannot connect to CnCServer"
            break

    if debugBits is not None:
        print "DebugBits are now 0x%0x" % debugBits
