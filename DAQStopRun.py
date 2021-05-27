#!/usr/bin/env python
"""
`pdaq stoprun` script which talks directly to CnCServer to stop a run
NOTE: this is an emergency-only script used during rare I3Live failures
"""

from __future__ import print_function

import sys

from DAQConst import DAQPort
from DAQRPC import RPCClient
from i3helper import read_input
from utils.Machineid import Machineid

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


def add_arguments(parser):
    "Add command-line arguments"

    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help="Don't check the host type for run permission")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Verbose mode")
    parser.add_argument("runset", nargs="*")


def stop_runset_with_prompt(rsid):
    """
    Ask user if the specified RunSet should be stopped,
    then stop the RunSet if they agree
    """

    try:
        state = cncrpc.rpc_runset_state(rsid)
    except:  # pylint: disable=bare-except
        state = "UNKNOWN"

    while True:
        reply = read_input("Are you sure you want to stop" +
                           " runset #%d (%s) without 'livecmd'? " %
                           (rsid, state))
        lreply = reply.strip().lower()
        if lreply in ("y", "ye", "yes"):
            try:
                cncrpc.rpc_runset_stop_run(rsid)
                print("Stopped runset #%d" % rsid)
            except:  # pylint: disable=bare-except
                print("Could not stop runset #%d: %s" %
                      (rsid, exc_string()), file=sys.stderr)
            break
        elif lreply in ("n", "no"):
            break
        print("Please answer 'yes' or 'no'", file=sys.stderr)


def stoprun(args):
    "Stop the current run"
    stop_ids = []

    cncrpc = RPCClient("localhost", DAQPort.CNCSERVER)

    try:
        rsids = cncrpc.rpc_runset_list_ids()
    except:  # pylint: disable=bare-except
        rsids = []

    if len(rsids) == 0:  # pylint: disable=len-as-condition
        raise SystemExit("There are currently no active runsets")

    list_rs = False
    if len(args.runset) > 0:  # pylint: disable=len-as-condition
        for rs_arg in args.runset:
            try:
                rsid = int(rs_arg)
            except ValueError:
                print("Argument \"%s\" is not a runset ID" % rs_arg,
                      file=sys.stderr)
                list_rs = True
                break

            if rsid not in rsids:
                print("\"%s\" is not a valid runset ID" % rs_arg,
                      file=sys.stderr)
                list_rs = True
                break

            stop_ids.append(rsid)
    elif len(rsids) == 1:
        stop_ids.append(rsids[0])

    if len(stop_ids) == 0:  # pylint: disable=len-as-condition
        print("Please specify a runset ID", file=sys.stderr)
        list_rs = False

    if list_rs:
        errmsg = "Valid runset IDs:"
        for rsid in rsids:
            errmsg += " %d" % rsid
        raise SystemExit(errmsg)

    for rsid in stop_ids:
        stop_runset_with_prompt(rsid)


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    if not args.nohostcheck:
        # exit if not running on expcont
        hostid = Machineid()
        if (not (hostid.is_control_host or
                 (hostid.is_unknown_host and hostid.is_unknown_cluster))):
            raise SystemExit("Are you sure you are emergency-stopping the run"
                             " on the correct host?")

    stoprun(args)


if __name__ == "__main__":
    main()
