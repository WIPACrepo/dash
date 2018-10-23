#!/usr/bin/env python

from __future__ import print_function

import sys

from DAQConst import DAQPort
from DAQRPC import RPCClient
from utils.Machineid import Machineid

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


# Python 2/3 compatibility hack
if sys.version_info >= (3, 0):
    read_input = input
else:
    read_input = raw_input


def add_arguments(parser):
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help="Don't check the host type for run permission")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Verbose mode")
    parser.add_argument("runset", nargs="*")


def stoprun(args):
    stopIds = []

    cncrpc = RPCClient("localhost", DAQPort.CNCSERVER)

    try:
        rsids = cncrpc.rpc_runset_list_ids()
    except:
        rsids = []

    if len(rsids) == 0:
        raise SystemExit("There are currently no active runsets")

    listRS = False
    if len(args.runset) > 0:
        for a in args.runset:
            try:
                n = int(a)
            except:
                print("Argument \"%s\" is not a runset ID" % a, file=sys.stderr)
                listRS = True
                break

            if n not in rsids:
                print("\"%s\" is not a valid runset ID" % a, file=sys.stderr)
                listRS = True
                break

            stopIds.append(n)
    elif len(rsids) == 1:
        stopIds.append(rsids[0])

    if len(stopIds) == 0:
        print("Please specify a runset ID", file=sys.stderr)
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
            reply = read_input("Are you sure you want to stop" +
                               " runset #%d (%s) without 'livecmd'? " %
                               (rsid, state))
            lreply = reply.strip().lower()
            if lreply == "y" or lreply == "yes":
                try:
                    cncrpc.rpc_runset_stop_run(rsid)
                    print("Stopped runset #%d" % rsid)
                except:
                    print("Could not stop runset #%d: %s" % \
                          (rsid, exc_string()), file=sys.stderr)
                break
            elif lreply == "n" or lreply == "no":
                break
            print("Please answer 'yes' or 'no'", file=sys.stderr)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()

    add_arguments(p)

    args = p.parse_args()

    if not args.nohostcheck:
        # exit if not running on expcont
        hostid = Machineid()
        if (not (hostid.is_control_host() or
                 (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
            raise SystemExit("Are you sure you are emergency-stopping the run"
                             " on the correct host?")

    stoprun(args)
