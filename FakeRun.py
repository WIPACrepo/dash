#!/usr/bin/env python

import sys,time
from exc_string import *
from random import random
from DAQLog import SocketLogger
from DAQRPC import RPCClient

set_exc_string_encoding("ascii")

class FakeRun:
    def __init__(self, logPort, compList, servername="localhost", portnum=8080):
	compDict = {}
	for c in compList:
	    compDict[c] = logPort

        cl = RPCClient(servername, portnum)
        try:
            setId = cl.rpc_runset_make(compDict)
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
    logPort = 4444
    compList = []

    i = 1
    while i < len(sys.argv):
	arg = sys.argv[i]
	i += 1

	if len(arg) > 1 and arg[0:1] == '-':
	    if arg[1:2] == 'l':
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
	FakeRun(logPort, compList)
    finally:
	logger.stopServing()
