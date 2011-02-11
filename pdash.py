#!/usr/bin/env python

import cmd, sys, traceback
from DAQConst import DAQPort
from DAQRPC import RPCClient

class Dash(cmd.Cmd):
    CMD_BEAN = "bean"
    CMD_HELP = "help"
    CMD_LS = "ls"

    CMDS = {
        CMD_BEAN : "get bean data",
        CMD_HELP : "print this message",
        CMD_LS : "list component info",
        }

    def __init__(self):
        self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)

        cmd.Cmd.__init__(self)

        self.prompt = "> "

    def __findComponentId(cls, compDict, compName):
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
    __findComponentId = classmethod(__findComponentId)


    def __listAll(self):
        ids = self.__cnc.rpc_runset_list_ids()
        compDict = self.__cnc.rpc_component_list()
        comps = self.__cnc.rpc_component_list_dicts(compDict.values())

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

    def __runCmdBean(self, args):
        "Get bean data"
        if len(args) == 0:
            print >>sys.stderr, "Please specify a component.bean.field"
            return

        compDict = self.__cnc.rpc_component_list()

        for c in args:
            bflds = c.split(".")

            if compDict.has_key(bflds[0]):
                compName = bflds[0]
                compId = compDict[compName]
            else:
                try:
                    compId = int(bflds[0])
                except ValueError:
                    compId = None

                compName = None
                if compId is not None:
                    for c in compDict.keys():
                        if compDict[c] == compId:
                            compName = c
                            break

                if compName is None:
                    print >>sys.stderr, "Unknown component \"%s\"" % bflds[0]

            if len(bflds) == 1:
                beanList = self.__cnc.rpc_component_list_beans(compId)

                print "%s beans:" % compName
                for b in beanList:
                    print "    " + b

                return

            beanName = bflds[1]
            if len(bflds) == 2:
                fldList = \
                    self.__cnc.rpc_component_list_bean_fields(compId, beanName)

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

    def do_bean(self, line):
        "Get bean data"
        try:
            self.__runCmdBean(line.split())
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

if __name__ == "__main__":
    Dash().cmdloop()
