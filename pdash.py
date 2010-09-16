#!/usr/bin/env python

import sys, traceback
from DAQConst import DAQPort
from DAQRPC import RPCClient

class Dash(object):
    def __init__(self):
        self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)

    def __listAll(self):
        ids = self.__cnc.rpc_runset_list_ids()
        cids = self.__cnc.rpc_component_list_ids()
        comps = self.__cnc.rpc_component_list_dicts(cids)

        if len(comps) > 0:
            print "Components:"
            self.__printComponents(comps, "  ")
            if len(ids) > 0:
                print

        if len(ids) > 0:
            numIds = len(ids)
            for i in range(numIds):
                rsid = ids[i]
                if i > 0: print
                state = self.__cnc.rpc_runset_state(rsid)
                print "Runset #%d: %s" % (rsid, state)

                rs = self.__cnc.rpc_runset_list(rsid)
                self.__printComponents(rs, "  ")

    def __printComponentDetails(self, idList=None):
        if idList is None:
            info = self.__cnc.rpc_component_connector_info()
        else:
            info = self.__cnc.rpc_component_connector_info(idList)
        print "Details:"
        for cdict in info:
            print "  #%s: %s#%d" % (cdict["id"], cdict["compName"],
                                    cdict["compNum"])
            if cdict.has_key("conn"):
                for conn in cdict["conn"]:
                    print "    %s *%d %s" % (conn["type"], conn["numChan"],
                                             conn["state"])
            elif cdict.has_key("error"):
                print "    %s" % cdict["error"]
            else:
                print "    Unknown error"

    def __printComponents(self, comps, indent):
        for cdict in comps:
            print "%s#%d: %s#%d (%s)" % \
                  (indent, cdict["id"], cdict["compName"],
                   cdict["compNum"], cdict["state"])

    def close(self):
        pass

    def eval(self, line):
        flds = line.split()
        if len(flds) == 0:
            return

        if flds[0] == "ls":
            if len(flds) == 1:
                self.__listAll()
            else:
                idList = []
                for cstr in flds[1:]:
                    if cstr == "*":
                        idList = None
                        break

                    try:
                        idList.append(int(cstr))
                    except ValueError:
                        print >>sys.stderr, "Bad component id \"%s\"" % cstr

                self.__printComponentDetails(idList)
        else:
            print >>sys.stderr, "Unknown command \"%s\"" % line

if __name__ == "__main__":
    dash = Dash()
    while True:
        try:
            line = raw_input("> ")
        except EOFError:
            break

        try:
            dash.eval(line)
        except:
            traceback.print_exc()

    dash.close()
