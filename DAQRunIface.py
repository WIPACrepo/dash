#!/usr/bin/env python

#
# Object to interface w/ DAQ run script
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
# $Id:$

from time import sleep, time
from datetime import datetime, timedelta
from DAQRPC import RPCClient
from locate_pdaq import find_pdaq_trunk
from os.path import join, exists
from xml.dom import minidom

class LabelConfigFileNotFoundException(Exception): pass
class MalformedLabelConfigException   (Exception): pass

def getElementSingleTagName(root, name):
    "Fetch a single element tag name of form <tagName>yowsa!</tagName>"
    elems = root.getElementsByTagName(name)
    if len(elems) != 1:
        raise MalformedLabelConfigException("Expected exactly one %s" % name)
    if len(elems[0].childNodes) != 1:
        raise MalformedLabelConfigException("Expected exactly one child node of %s" %name)
    return elems[0].childNodes[0].data

class DAQLabelParser:
    def __init__(self, configFile):
        if not exists(configFile): raise LabelConfigFileNotFound(configFile)
        self.configFile   = configFile
        self.dict         = {}
        self.defaultLabel = None
        parsed = minidom.parse(self.configFile)
        daqLabels = parsed.getElementsByTagName("daqLabels")
        if len(daqLabels) != 1: raise MalformedLabelConfigException(self.configFile)
        runs = daqLabels[0].getElementsByTagName("run")
        self.defaultLabel = getElementSingleTagName(daqLabels[0], "defaultLabel")
        for run in runs:
            alias = str(run.attributes["alias"].value)
            runConfig   = getElementSingleTagName(run, "runConfig")
            description = getElementSingleTagName(run, "description")
            runMode     = getElementSingleTagName(run, "runMode")
            self.dict[alias] = ( str(runConfig), str(description), str(runMode) )
    
class DAQRunIface(object):
    START_TRANSITION_SECONDS    = 200
    STOP_TRANSITION_SECONDS     = 120
    RECOVERY_TRANSITION_SECONDS = 200
    RELEASE_TRANSITION_SECONDS  = 120
    
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
        return self.rpc.rpc_daq_summary_xml()
    
    def release(self):
        """
        Release DAQ component resources (run sets) back to CnC Server
        Use for "standalone" instances of DAQ (i.e. non-'Experiment Control')
        """
        self.rpc.rpc_release_runsets()
        return DAQRunIface.RELEASE_TRANSITION_SECONDS
    
    def getDaqLabels(self):
        home = find_pdaq_trunk()
        parser = DAQLabelParser(join(home, "dash", "config", "daqlabels.xml"))
        return parser.dict, parser.defaultLabel
    
if __name__ == "__main__":
    iface = DAQRunIface()
    print iface.getDaqLabels()
