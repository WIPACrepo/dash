#!/usr/bin/env python

import optparse, socket, sys, traceback

from DAQConst import DAQPort
from DAQRPC import RPCClient
from RunSet import RunSet
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
    op = optparse.OptionParser()
    op.add_option("-d", "--debugFlags", type="string", dest="debugFlags",
                  action="store", default=None,
                  help="List active runset IDs")
    op.add_option("-l", "--list", dest="list",
                  action="store_true", default=False,
                  help="List active runset IDs")
    op.add_option("-L", "--list-flags", dest="listFlags",
                  action="store_true", default=False,
                  help="List debugging flags")

    opt,args = op.parse_args()

    rpc = RPCClient("localhost", DAQPort.CNCSERVER)

    if opt.list:
        try:
            idList = rpc.rpc_runset_listIDs()
            print "Run set IDs:"
            for i in idList:
                print "  %d" % i
        except socket.error, err:
            print >>sys.stderr, "Cannot connect to CnCServer"

    if opt.listFlags:
        keys = RunSetDebug.NAME_MAP.keys()
        keys.sort()
        print "Debugging flags:"
        for k in keys:
            print "  " + k

    if opt.list or opt.listFlags:
        raise SystemExit

    if opt.debugFlags is None:
        bits = RunSetDebug.ALL
    else:
        bits = parseFlags(opt.debugFlags)

    debugBits = None
    for a in args:
        try:
            id = int(a)
        except ValueError:
            print >>sys.stderr, "Ignoring bad ID \"%s\"" % a
            continue

        try:
            print "Runset#%d -> 0x%0x" % (id, bits)
            debugBits = rpc.rpc_runset_debug(id, bits)
        except socket.error, err:
            print >>sys.stderr, "Cannot connect to CnCServer"
            break

    if debugBits is not None:
        print "DebugBits are now 0x%0x" % debugBits
