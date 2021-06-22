#!/usr/bin/env python

from __future__ import print_function

import socket

from DAQConst import DAQPort
from DAQRPC import RPCClient
from LiveImports import SERVICE_NAME
from utils.Machineid import Machineid


LINE_LENGTH = 78


def add_arguments(parser):
    "Add command-line arguments"

    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help="Don't check the host type for run permission")
    parser.add_argument("-n", "--numeric", dest="numeric",
                        action="store_true", default=False,
                        help=("Show IP addresses instead of hostnames"
                              " in verbose output"))
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print detailed list")


def dump_comp(comp, num_list, indent, indent2):
    """Dump list of component instances, breaking long lists across lines"""

    if comp is None or len(num_list) == 0:  # pylint: disable=len-as-condition
        return

    if len(num_list) == 1 and num_list[0] == 0:
        print(indent + indent2 + comp)
        return

    num_str = None
    prev_num = -1
    in_range = False
    for num in num_list:
        if num_str is None:
            num_str = str(num)
        else:
            if prev_num + 1 == num:
                if not in_range:
                    in_range = True
            else:
                if in_range:
                    num_str += "-" + str(prev_num)
                    in_range = False
                num_str += " " + str(num)
        prev_num = num
    if num_str is None:
        num_str = ""
    elif in_range:
        num_str += "-" + str(prev_num)

    plural = get_plural(len(num_list))
    front = "%s%s%d %s%s: " % (indent, indent2, len(num_list), comp, plural)
    front_len = len(front)
    front_cleared = False

    while num_str != "":
        # if list of numbers fits on the line, print it
        if front_len + len(num_str) < LINE_LENGTH:
            print(front + num_str)
            break

        # look for break point
        tmp_len = LINE_LENGTH - front_len
        if tmp_len >= len(num_str):
            tmp_len = len(num_str) - 1
        while tmp_len > 0 and num_str[tmp_len] != " ":
            tmp_len -= 1
        if tmp_len == 0:
            tmp_len = LINE_LENGTH - front_len
            while tmp_len < len(num_str) and num_str[tmp_len] != " ":
                tmp_len += 1

        # split line at break point
        print(front + num_str[0:tmp_len])

        # set num_str to remainder of string and strip leading whitespace
        num_str = num_str[tmp_len:]
        while num_str != "" and num_str[0] == " ":
            num_str = num_str[1:]

        # after first line, set front string to whitespace
        if not front_cleared:
            front = " " * len(front)
            front_cleared = True


def get_plural(num):
    if num == 1:
        return ""
    return "s"


def list_terse(comp_list, indent, indent2):
    prev_state = None
    prev_comp = None

    num_list = []
    for comp in sorted(comp_list, key=lambda x: (x["state"], x["compName"],
                                                 x["compNum"])):
        state_changed = prev_state != comp["state"]
        comp_changed = prev_comp != comp["compName"]
        if comp_changed or state_changed:
            dump_comp(prev_comp, num_list, indent, indent2)
            prev_comp = comp["compName"]
            num_list = []
        if state_changed:
            prev_state = comp["state"]
            print(indent + prev_state)
        num_list.append(comp["compNum"])
    dump_comp(prev_comp, num_list, indent, indent2)


def list_verbose(comp_list, indent, indent2, use_numeric=True):
    for comp in sorted(comp_list, key=lambda x: (x["state"], x["compName"],
                                                 x["compNum"])):
        if use_numeric:
            hostname = comp["host"]
        else:
            hostname = socket.getfqdn(comp["host"])
            idx = hostname.find(".")
            if idx > 0:
                hostname = hostname[:idx]

        print("%s%s#%d %s#%d at %s:%d M#%d %s" %
              (indent, indent2, comp["id"], comp["compName"], comp["compNum"],
               hostname, comp["rpcPort"], comp["mbeanPort"], comp["state"]))


def print_status(args):
    cncrpc = RPCClient("localhost", DAQPort.CNCSERVER)

    try:
        ncomps = cncrpc.rpc_component_count()
    except:  # pylint: disable=bare-except
        ncomps = 0

    try:
        complist = cncrpc.rpc_component_list_dicts([], False)
    except:  # pylint: disable=bare-except
        complist = []

    try:
        nsets = cncrpc.rpc_runset_count()
    except:  # pylint: disable=bare-except
        nsets = 0

    try:
        ids = cncrpc.rpc_runset_list_ids()
    except:  # pylint: disable=bare-except
        ids = []

    try:
        vers_info = cncrpc.rpc_version()
        vers = " (%s:%s)" % (vers_info["release"], vers_info["repo_rev"])
    except:  # pylint: disable=bare-except
        vers = " ??"

    print("CNC %s:%d%s" % ("localhost", DAQPort.CNCSERVER, vers))

    indent = "    "

    if indent == "":
        indent2 = "  "
    else:
        indent2 = indent

    print("=======================")
    print("%d unused component%s" % (ncomps, get_plural(ncomps)))
    if args.verbose or args.numeric:
        list_verbose(complist, indent, indent2, args.numeric)
    else:
        list_terse(complist, indent, indent2)

    print("-----------------------")
    print("%d run set%s" % (nsets, get_plural(nsets)))
    for runid in ids:
        cfg = cncrpc.rpc_runset_configname(runid)
        lst = cncrpc.rpc_runset_list(runid)
        print("%sRunSet#%d (%s)" % (indent, runid, cfg))
        if args.verbose or args.numeric:
            list_verbose(lst, indent, indent2, args.numeric)
        else:
            list_terse(lst, indent, indent2)

    liverpc = RPCClient("localhost", DAQPort.DAQLIVE)

    try:
        lst = liverpc.rpc_status(SERVICE_NAME)
    except:  # pylint: disable=bare-except
        lst = "???"

    print("=======================")
    print("DAQLive %s:%d" % ("localhost", DAQPort.DAQLIVE))
    print("=======================")
    print("Status: %s" % lst)


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
            raise SystemExit("Are you sure you are checking status"
                             " on the correct host?")

    print_status(args)


if __name__ == "__main__":
    main()
