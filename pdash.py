#!/usr/bin/env python

import cmd
import sys
import traceback
from DAQConst import DAQPort
from DAQRPC import RPCClient


class Dash(cmd.Cmd):
    def __init__(self):
        self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)

        cmd.Cmd.__init__(self)

        self.prompt = "> "

    @staticmethod
    def __findComponentId(compDict, compName):
        if not compDict.has_key(compName):
            if compName.endswith("#0") or compName.endswith("-0"):
                compName = compName[:-2]
            elif compName.find("-") > 0:
                flds = compName.split("-")
                if len(flds) > 1:
                    compName = "#".join(flds)

        if compDict.has_key(compName):
            return compDict[compName]

        raise ValueError("Unknown component \"%s\"" % compName)

    def __findComponentFromString(self, compDict, compStr):
        compName = None
        compId = None

        if compStr is not None and compDict is not None:
            if compDict.has_key(compStr):
                compName = compStr
                compId = compDict[compName]
            else:
                try:
                    compId = int(compStr)
                except ValueError:
                    compId = None

                if compId is not None:
                    for c in compDict.keys():
                        if compDict[c] == compId:
                            compName = c
                            break

        return (compName, compId)

    def __listAll(self):
        ids = self.__cnc.rpc_runset_list_ids()
        compDict = self.__cnc.rpc_component_list()
        comps = self.__cnc.rpc_component_list_dicts(compDict.values(), False)

        if len(comps) > 0:
            print "Components:"
            self.__printComponents(comps, "  ")
            if len(ids) > 0:
                print

        if len(ids) > 0:
            numIds = len(ids)
            for i in range(numIds):
                rsid = ids[i]
                if i > 0:
                    print
                state = self.__cnc.rpc_runset_state(rsid)
                print "Runset #%d: %s" % (rsid, state)

                rs = self.__cnc.rpc_runset_list(rsid)
                self.__printComponents(rs, "  ")

    def __printComponentDetails(self, idList=None):
        if idList is None:
            info = self.__cnc.rpc_component_connector_info()
        else:
            info = self.__cnc.rpc_component_connector_info(idList, False)
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

    def __runCmdBean(self, args):
        "Get bean data"
        if len(args) == 0:
            print >>sys.stderr, "Please specify a component.bean.field"
            return

        compDict = self.__cnc.rpc_component_list()
        rsDict = None

        for c in args:
            bflds = c.split(".")

            print "Find \"%s\" in %s" % (bflds[0], compDict.keys())
            (compName, compId) = \
                self.__findComponentFromString(compDict, bflds[0])
            if compName is None:
                if rsDict is None:
                    rsDict = {}

                    ids = self.__cnc.rpc_runset_list_ids()
                    for rsid in ids:
                        rsComps = self.__cnc.rpc_runset_list(rsid)

                        rsDict[rsid] = {}
                        for sub in rsComps:
                            if sub["compNum"] == 0:
                                nm = sub["compName"]
                            else:
                                nm = sub["compName"] + "#" + \
                                    str(sub["compNum"])
                            rsDict[rsid][nm] = sub["id"]
                        if compName is None:
                            print "Find \"%s\" in RS#%d %s" % \
                                (bflds[0], rsid, rsDict[rsid].keys())
                            (compName, compId) = \
                                self.__findComponentFromString(rsDict[rsid],
                                                               bflds[0])

            if compName is None:
                print >>sys.stderr, "Unknown component \"%s\"" % bflds[0]
                return

            if len(bflds) == 1:
                beanList = self.__cnc.rpc_component_list_beans(compId, True)

                print "%s beans:" % compName
                for b in beanList:
                    print "    " + b

                return

            beanName = bflds[1]
            if len(bflds) == 2:
                fldList = \
                    self.__cnc.rpc_component_list_bean_fields(compId, beanName,
                                                              True)

                print "%s bean %s fields:" % (compName, beanName)
                for f in fldList:
                    print "    " + f

                return

            fldName = bflds[2]
            if len(bflds) == 3:
                val = self.__cnc.rpc_component_get_bean_field(compId, beanName,
                                                              fldName)
                print "%s bean %s field %s: %s" % \
                    (compName, beanName, fldName, val)

                return

            print >>sys.stderr, "Bad component.bean.field \"%s\"" % c

    def __runCmdClose(self, args):
        fdList = []
        for a in args:
            if a.find("-") < 0:
                try:
                    i = int(a)
                except:
                    print >>sys.stderr, "Bad file %s" % a
                    break

                fdList.append(i)
            else:
                (a1, a2) = a.split("-")
                try:
                    i1 = int(a1)
                    i2 = int(a2)
                except:
                    print >>sys.stderr, "Bad range %s" % a
                    break

                for i in range(i1, i2 + 1):
                    fdList.append(i)

        self.__cnc.rpc_close_files(fdList)

    def __runCmdList(self, args):
        "List component info"
        if len(args) == 0:
            self.__listAll()
            return

        compDict = None
        idList = []
        for cstr in args:
            if cstr == "*":
                idList = None
                break

            try:
                id = int(cstr)
            except ValueError:
                if compDict is None:
                    compDict = self.__cnc.rpc_component_list()

                try:
                    id = self.__findComponentId(compDict, cstr)
                except ValueError:
                    print >>sys.stderr, "Unknown component \"%s\"" % cstr
                    continue

            idList.append(id)

        self.__printComponentDetails(idList)

    def __runCmdOpenFiles(self, args):
        "List open files"
        for of in self.__cnc.rpc_list_open_files():
            try:
                print "  %4.4s %6.6s %s%s" % tuple(of)
            except:
                print "  ??? %s" % of

    def do_bean(self, line):
        "Get bean data"
        try:
            self.__runCmdBean(line.split())
        except:
            traceback.print_exc()

    def do_close(self, line):
        "Close open file"
        try:
            self.__runCmdClose(line.split())
        except:
            traceback.print_exc()

    def do_EOF(self, line):
        print
        return True

    def do_list(self, line):
        "List component info"
        try:
            self.__runCmdList(line.split())
        except:
            traceback.print_exc()

    def do_ls(self, args):
        "List component info"
        return self.do_list(args)

    def do_openfiles(self, line):
        "List open files"
        try:
            self.__runCmdOpenFiles(line.split())
        except:
            traceback.print_exc()

if __name__ == "__main__":
    Dash().cmdloop()
