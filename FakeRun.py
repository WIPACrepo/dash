#!/usr/bin/env python

import sys,time
from exc_string import *
from random import random
from DAQLog import SocketLogger
from DAQRPC import RPCClient

set_exc_string_encoding("ascii")

class FakeRun:
    def __init__(self, logPort, compList, delay,
                 servername="localhost", portnum=8080):
        cl = RPCClient(servername, portnum)
        try:
            setId = cl.rpc_runset_make(compList)
        except Exception, e:
            print "Remote operation failed: %s" % e
            sys.exit(1)

        print "Created runset #" + str(setId)

        logList = []
        for name in compList:
            pound = name.rfind('#')
            if pound < 0:
                num = 0
            else:
                num = int(name[pound+1:])
                name = name[0:pound]

            logList.append([name, num, logPort, 'info'])

        cl.rpc_runset_log_to(setId, '127.0.0.1', logList)

        runNum = int(random() * 100000)

        try:
            try:
                cl.rpc_runset_configure(setId, 'hub1001sim')
                cl.rpc_runset_start_run(setId, runNum)
                for i in range(1,delay):
                    cl.rpc_runset_status(setId)
                    time.sleep(1)
                cl.rpc_runset_stop_run(setId)
            except Exception, e:
                print exc_string()
                raise e
        finally:
            cl.rpc_runset_break(setId)
            cl.rpc_close_log()

if __name__ == "__main__":
    logPort = 4444
    compList = []
    delay = 20

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        i += 1

        if len(arg) > 1 and arg[0:1] == '-':
            if arg[1:2] == 'd':
                if len(arg) > 2:
                    delayStr = int(arg[2:])
                else:
                    delayStr = sys.argv[i]
                    i += 1

                try:
                    delay = int(delayStr)
                except:
                    sys.stderr.write("Bad delay length '%s'\n" % delayStr)
                    sys.exit(1)

                continue

            elif arg[1:2] == 'l':
                if len(arg) > 2:
                    portStr = arg[2:]
                else:
                    portStr = sys.argv[i]
                    i += 1

                try:
                    logPort = int(portStr)
                except:
                    sys.stderr.write("Bad logging port '%s'\n" % portStr)
                    sys.exit(1)

                continue

        compList.append(arg)

    logger = SocketLogger(logPort, 'all-components', None)
    try:
        logger.startServing()
        FakeRun(logPort, compList, delay)
    finally:logger.stopServing()
