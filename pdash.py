#!/usr/bin/env python

from __future__ import print_function

import argparse
import cmd
import sys
import traceback
from DAQConst import DAQPort
from DAQRPC import RPCClient


class Dash(cmd.Cmd):
    "pDAQ interactive shell"
    def __init__(self):
        self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)

        cmd.Cmd.__init__(self)

        self.prompt = "> "

    @staticmethod
    def __find_component_id(comp_dict, comp_name):
        try:
            return int(comp_name)
        except ValueError:
            pass

        if comp_name not in comp_dict:
            if comp_name.endswith("#0") or comp_name.endswith("-0"):
                comp_name = comp_name[:-2]
            elif comp_name.find("-") > 0:
                flds = comp_name.split("-")
                if len(flds) > 1:
                    comp_name = "#".join(flds)

        if comp_name in comp_dict:
            return comp_dict[comp_name]

        raise ValueError("Unknown component \"%s\" (not %s)" %
                         (comp_name, list(comp_dict.keys())))

    @classmethod
    def __find_component_from_string(cls, comp_dict, comp_str):
        comp_name = None
        comp_id = None

        if comp_str is not None and comp_dict is not None:
            sep = comp_str.find('#')
            if sep > 0:
                try:
                    comp_num = int(comp_str[sep+1:])
                    comp_name = comp_str[:sep]
                    if comp_num == 0 and comp_name in comp_dict:
                        return (comp_name, comp_dict[comp_name])
                except ValueError:
                    pass

            if comp_str in comp_dict:
                comp_name = comp_str
                comp_id = comp_dict[comp_name]
            else:
                try:
                    comp_id = int(comp_str)
                except ValueError:
                    return (None, None)

                if comp_id is not None:
                    for comp in list(comp_dict.keys()):
                        if comp_dict[comp] == comp_id:
                            comp_name = comp
                            break

        return (comp_name, comp_id)

    def __list_all(self):
        ids = self.__cnc.rpc_runset_list_ids()
        comp_dict = self.__cnc.rpc_component_list()
        comps = self.__cnc.rpc_component_list_dicts(list(comp_dict.values()),
                                                    False)

        if len(comps) > 0:
            print("Components:")
            self.__print_components(comps, "  ")
            if len(ids) > 0:
                print()

        if len(ids) > 0:
            num_ids = len(ids)
            for i in range(num_ids):
                rsid = ids[i]
                if i > 0:
                    print()
                state = self.__cnc.rpc_runset_state(rsid)
                print("Runset #%d: %s" % (rsid, state))

                rset = self.__cnc.rpc_runset_list(rsid)
                self.__print_components(rset, "  ")

    def __print_component_details(self, id_list=None):
        if id_list is None:
            info = self.__cnc.rpc_component_connector_info()
        else:
            info = self.__cnc.rpc_component_connector_info(id_list, False)
        print("Details:")
        for cdict in info:
            print("  #%s: %s#%d" % (cdict["id"], cdict["compName"],
                                    cdict["compNum"]))
            if "conn" in cdict:
                for conn in cdict["conn"]:
                    print("    %s *%d %s" % (conn["type"], conn["numChan"],
                                             conn["state"]))
            elif "error" in cdict:
                print("    %s" % cdict["error"])
            else:
                print("    Unknown error")

    @classmethod
    def __print_components(cls, comps, indent):
        for cdict in comps:
            print("%s#%d: %s#%d (%s)" % \
                  (indent, cdict["id"], cdict["compName"],
                   cdict["compNum"], cdict["state"]))

    def __run_cmd_bean(self, args):
        "Get bean data"
        if len(args) == 0:
            print("Please specify a component.bean.field", file=sys.stderr)
            return

        comp_dict = self.__cnc.rpc_component_list()
        rs_dict = None

        for comp in args:
            bflds = comp.split(".")

            (comp_name, comp_id) = \
                self.__find_component_from_string(comp_dict, bflds[0])
            if comp_name is None:
                if rs_dict is None:
                    rs_dict = {}

                    ids = self.__cnc.rpc_runset_list_ids()
                    for rsid in ids:
                        rs_comps = self.__cnc.rpc_runset_list(rsid)

                        rs_dict[rsid] = {}
                        for sub in rs_comps:
                            if sub["compNum"] == 0:
                                name = sub["compName"]
                            else:
                                name = "%s#%s" % (sub["compName"],
                                                  sub["compNum"])
                            rs_dict[rsid][name] = sub["id"]

                for rsid in rs_dict:
                    (comp_name, comp_id) = \
                               self.__find_component_from_string(rs_dict[rsid],
                                                                 bflds[0])
                    if comp_name is not None:
                        break

            if comp_name is None:
                print("Unknown component \"%s\"" % bflds[0], file=sys.stderr)
                return

            if len(bflds) == 1:
                bean_list = self.__cnc.rpc_component_list_beans(comp_id, True)

                print("%s beans:" % comp_name)
                for bean in bean_list:
                    print("    %s" % str(bean))

                return

            bean_name = bflds[1]
            if len(bflds) == 2:
                fld_list = \
                        self.__cnc.rpc_component_list_bean_fields(comp_id,
                                                                  bean_name,
                                                                  True)

                print("%s bean %s fields:" % (comp_name, bean_name))
                for fld in fld_list:
                    print("    %s" % str(fld))

                return

            fld_name = bflds[2]
            if len(bflds) == 3:
                val = self.__cnc.rpc_component_get_bean_field(comp_id,
                                                              bean_name,
                                                              fld_name, True)
                print("%s bean %s field %s: %s" % \
                    (comp_name, bean_name, fld_name, val))

                return

            print("Bad component.bean.field \"%s\"" % comp, file=sys.stderr)

    def __run_cmd_close(self, args):
        fd_list = []
        for arg in args:
            if arg.find("-") < 0:
                try:
                    i = int(arg)
                except:
                    print("Bad file %s" % (arg, ), file=sys.stderr)
                    break

                fd_list.append(i)
            else:
                (arg1, arg2) = arg.split("-")
                try:
                    idx1 = int(arg1)
                    idx2 = int(arg2)
                except:
                    print("Bad range %s" % arg, file=sys.stderr)
                    break

                for idx in range(idx1, idx2 + 1):
                    fd_list.append(idx)

        self.__cnc.rpc_close_files(fd_list)

    def __run_cmd_list(self, args):
        "List component info"
        if len(args) == 0:
            self.__list_all()
            return

        comp_dict = None
        id_list = []
        for cstr in args:
            if cstr == "*":
                id_list = None
                break

            # try to add index number
            try:
                id_list.append(int(cstr))
                continue
            except ValueError:
                pass

            if comp_dict is None:
                comp_dict = self.__cnc.rpc_component_list()

            try:
                comp_id = self.__find_component_id(comp_dict, cstr)
                id_list.append(comp_id)
                continue
            except ValueError:
                pass

            if cstr.find(".") > 0:
                self.__run_cmd_bean((cstr, ))
                continue

            print("Unknown component \"%s\" YYY" % cstr, file=sys.stderr)
            continue

        if len(id_list) > 0:
            self.__print_component_details(id_list)

    def __run_cmd_open_files(self, args):
        "List open files"
        for opn in self.__cnc.rpc_list_open_files():
            try:
                print("  %4.4s %6.6s %s%s" % tuple(opn))
            except:
                print("  ??? %s" % opn)

    def do_bean(self, line):
        "Get bean data"
        try:
            self.__run_cmd_bean(line.split())
        except:
            traceback.print_exc()

    def do_close(self, line):
        "Close open file"
        try:
            self.__run_cmd_close(line.split())
        except:
            traceback.print_exc()

    @classmethod
    def do_EOF(cls, line):
        "Finish this session"
        print()
        return True

    def do_list(self, line):
        "List component info"
        try:
            self.__run_cmd_list(line.split())
        except:
            traceback.print_exc()

    def do_ls(self, args):
        "List component info"
        return self.do_list(args)

    def do_openfiles(self, line):
        "List open files"
        try:
            self.__run_cmd_open_files(line.split())
        except:
            traceback.print_exc()


def process_commands(commands, verbose=False):
    "Process all commands"
    dash = Dash()

    for arg in commands:
        argsplit = arg.split(" ", 1)
        if len(argsplit) == 0:
            print("Ignoring empty command \"%s\"" % arg, file=sys.stderr)
            continue

        acmd = argsplit[0]
        if len(argsplit) == 1:
            remainder = ""
        else:
            remainder = argsplit[1]

        try:
            if verbose:
                print(arg)
            getattr(dash, "do_" + acmd)(remainder)
        except AttributeError:
            print("Unknown command \"%s\"" % acmd, file=sys.stderr)
        except:
            traceback.print_exc()


def main():
    "Main program"
    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--command", dest="command", action="append",
                        help="Command to run (may be specified multiple times)")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true",
                        help="Print command before running it")

    args = parser.parse_args()

    if args.command is None or len(args.command) == 0:
        Dash().cmdloop()
    else:
        process_commands(args.command)


if __name__ == "__main__":
    main()
