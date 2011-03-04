#!/usr/bin/env python

import optparse, os, sys

from DAQConst import DAQPort
from DAQRPC import RPCClient

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID  = "$Id$"

if __name__ == "__main__":
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s " \
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Verbose mode")

    opt, args = p.parse_args()

    stopIds = []

    cncrpc = RPCClient("localhost", DAQPort.CNCSERVER)

    try:
        rsids = cncrpc.rpc_runset_list_ids()
    except:
        rsids = []

    if len(rsids) == 0:
        raise SystemExit("There are currently no active runsets")

    listRS = False
    if len(args) > 0:
        for a in args:
            try:
                n = int(a)
            except:
                print >>sys.stderr, "Argument \"%s\" is not a runset ID" % a
                listRS = True
                break

            if not n in rsids:
                print >>sys.stderr, "\"%s\" is not a valid runset ID" % a
                listRS = True
                break

            stopIds.append(n)
    elif len(rsids) == 1:
        stopIds.append(rsids[0])

    if len(stopIds) == 0:
        print >>sys.stderr, "Please specify a runset ID"
        listRS = False

    if listRS:
        errMsg = "Valid runset IDs:"
        for rsid in rsids:
            errMsg += " %d" % rsid
        raise SystemExit(errMsg)

    for rsid in stopIds:
        try:
            state = cncrpc.rpc_runset_state(rsid)
        except:
            state = "UNKNOWN"
        while True:
            reply = raw_input("Are you sure you want to stop" +
                              " runset #%d (%s)? " % (rsid, state))
            lreply = reply.strip().lower()
            if lreply == "y" or lreply == "yes":
                try:
                    cncrpc.rpc_runset_stop_run(rsid)
                    print "Stopped runset #%d" % rsid
                except:
                    print >>sys.stderr, "Could not stop runset #%d: %s" % \
                          (rsid, exc_string())
                break
            elif lreply == "n" or lreply == "no":
                break
            print >>sys.stderr, "Please answer 'yes' or 'no'"
