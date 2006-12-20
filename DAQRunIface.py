#!/usr/bin/env python

#
# Object to interface w/ DAQ run script
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
# $Id:$

from time import sleep, time
from datetime import datetime, timedelta

class DAQRunIface(object):
    START_TRANSITION_SECONDS    = 200
    STOP_TRANSITION_SECONDS     = 100
    RECOVERY_TRANSITION_SECONDS = 200
    
    def __init__(self, daqhost="localhost", daqport=8081):
        "Constructor - instantiate an RPC connection to DAQRun.py"
        self.rpc = RPCClient(daqhost, int(daqport))

    def start(self, r, config):
        "Tell DAQRun to start a run"
        self.rpc.rpc_start_run(r, 0, config)
        return DAQRunIface.START_TRANSITION_SECONDS
    
    def stop(self):
        "Tell DAQRun to stop a run"
        self.rpc.rpc_stop_run()
        return DAQRunIface.STOP_TRANSITION_SECONDS
    
    def recover(self):
        "Tell DAQRun to recover from an error and go to STOPPED state"
        self.rpc.rpc_recover()
        return DAQRunIface.RECOVERY_TRANSITION_SECONDS
    
    def getState(self):
        "Get current DAQ state"
        return self.rpc.rpc_run_state()
    def flasher(self, *info):
        "Tell DAQ to flash DOMs"
        pass
    def getSummary(self):
        "Get component summary from DAQRun"
        return "<daq/>"
    
