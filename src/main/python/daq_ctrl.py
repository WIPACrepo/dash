SYSTEM = 'daq'

import os
import sys
originalPath = sys.path
sys.path = []
sys.path.extend(originalPath)
CWD = os.getcwd()
if ('dash' == os.path.basename(CWD)):
    DASH_PATH = CWD
else:
    DASH_PATH = os.path.join(CWD,
                             'dash')
sys.path.append(os.path.normpath(DASH_PATH))
import DAQRunIface
sys.path = originalPath



import ec.states

import os
import socket
import time

instance = None

def getInstance():
    global instance
    if (None == instance):
        instance = DAQCtrl()
    return instance


ANVIL_FILES = os.path.join(os.environ['HOME'],
                           '.anvil')
TEST_FILES = os.path.join(ANVIL_FILES,
                          'test')
SUMMARY_FILE = os.path.join(TEST_FILES,
                            SYSTEM + '.summary')

XML_DATETIME_FORMAT = '%a %b %d %H:%M:%S %Z %Y'


STATE_MAPPING = {
    'STOPPED' : ec.states.STOPPED,
    'STARTING' : ec.states.STARTING,
    'RUNNING' : ec.states.STARTED,
    'STOPPING' : ec.states.STOPPING,
    'ERROR' : ec.states.ERROR,
    'RECOVERING' : ec.states.RECOVERING,
}

class DAQCtrl:

    def __init__(self):
        self.daqiface = DAQRunIface.DAQRunIface('localhost',
                                                9000)
        self.errorMsg = None


    def flasher(self,
                flasherConfiguration,
                subrunNumber):
        "Changes the current DAQ run to use the specified configuration"
        try:
            return self.daqiface.flasher(flasherConfiguration,
                                         subrunNumber)
        except socket.error:
            return 0


    def getDaqLabels(self):
        (labels, default) =  self.daqiface.getDaqLabels()
        labels['sps-icecube-amanda-noswt-002'] = ('sps-icecube-amanda-noswt-002',
                                                  'Unknown')
	labels['sps-icecube-only-001'] = ('sps-icecube-only-001', 'Unknown')
        return labels, default


    def getState(self):
        "Return the current state of the sub-system."
        try:
            return STATE_MAPPING[self.daqiface.getState()]
        except KeyError:
            return ec,states.UNKNOWN
        except socket.error:
            self.errorMsg = "DAQ not available"
            return ec.states.ERROR
        

    def getSummary(self):
        "Returns an XML snippet containing DAQ summary information"
        try:
            return self.daqiface.getSummary()
        except socket.error:
            return 0


    def recover(self):
        "Recovers the sub-system from an ERROR state."
        try:
            return self.daqiface.recover()
        except socket.error:
            return 0


    def start(self,
              runNumber,
              configKey):
        "Starts the DAQ sub-system running."
        try:
            result = self.daqiface.start(runNumber,
                                         configKey)
        except socket.error:
            return 0
        return result



    def stop(self):
        "Stops the DAQ sub-system running."
        try:
            return self.daqiface.stop()
        except socket.error:
            return 0
