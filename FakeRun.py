#!/usr/bin/env python

import sys,time
from exc_string import *
from random import random
from DAQLog import SocketLogger
from DAQRPC import RPCClient

set_exc_string_encoding("ascii")

class FakeRun:
    def __init__(self, compList, servername="localhost", portnum=8080):
        cl = RPCClient(servername, portnum)
        try:
            setId = cl.rpc_runset_make(compList)
        except Exception, e:
            print "Remote operation failed: %s" % e
            sys.exit(1)

        print "Created runset #" + str(setId)

        runNum = int(random() * 100000)

        try:
            try:
                cl.rpc_runset_configure(setId)
                cl.rpc_runset_start_run(setId, runNum)
                for i in range(1,20):
                    cl.rpc_runset_status(setId)
                    time.sleep(1)
                cl.rpc_runset_stop_run(setId)
            except Exception, e:
                print exc_string()
                raise e
        finally:
            cl.rpc_runset_break(setId)

if __name__ == "__main__":
    compList = []

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        i += 1
        compList.append(arg)

    FakeRun(compList)
