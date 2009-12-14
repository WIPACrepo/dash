#!/usr/bin/env python

#
# Object to interface w/ DAQ run script
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
# $Id: DAQRunIface.py 4799 2009-12-14 21:17:26Z dglo $

from DAQRPC import RPCClient
from os.path import join, exists
from os import environ
from xml.dom import minidom
from DAQConfig import DAQConfig
from re import sub
from types import DictType

class LabelConfigFileNotFound(Exception): pass
class MalformedLabelConfig   (Exception): pass
class MalformedFlasherInput  (Exception): pass

def getElementSingleTagName(root, name):
    "Fetch a single element tag name of form <tagName>yowsa!</tagName>"
    elems = root.getElementsByTagName(name)
    if len(elems) != 1:
        raise MalformedLabelConfig("Expected exactly one %s" % name)
    if len(elems[0].childNodes) != 1:
        raise MalformedLabelConfig("Expected exactly one child node of %s" %name)
    return elems[0].childNodes[0].data

class DAQLabelParser(object):
    def __init__(self, configFile):
        if not exists(configFile): raise LabelConfigFileNotFound(configFile)
        self.configFile   = configFile
        self.dict         = {}
        self.defaultLabel = None
        parsed = minidom.parse(self.configFile)
        daqLabels = parsed.getElementsByTagName("daqLabels")
        if len(daqLabels) != 1: raise MalformedLabelConfig(self.configFile)
        runs = daqLabels[0].getElementsByTagName("run")
        self.defaultLabel = getElementSingleTagName(daqLabels[0], "defaultLabel")
        for run in runs:
            alias = str(run.attributes["alias"].value)
            runConfig   = getElementSingleTagName(run, "runConfig")
            description = getElementSingleTagName(run, "description")
            runMode     = getElementSingleTagName(run, "runMode")
            self.dict[alias] = ( str(runConfig), str(description), str(runMode) )
    
class DAQRunIface(object):
    START_TRANSITION_SECONDS    = 300
    STOP_TRANSITION_SECONDS     = 300
    RECOVERY_TRANSITION_SECONDS = 300
    RELEASE_TRANSITION_SECONDS  = 300
    
    def __init__(self, daqhost="localhost", daqport=8081):
        "Constructor - instantiate an RPC connection to DAQRun.py"

        # Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
        if environ.has_key("PDAQ_HOME"):
            self.__home = environ["PDAQ_HOME"]
        else:
            from locate_pdaq import find_pdaq_trunk
            self.__home = find_pdaq_trunk()

        self.__rpc = RPCClient(daqhost, int(daqport))
        self.__id = self.__rpc.rpc_ping()

    def start(self, r, config, logInfo=()):
        "Tell DAQRun to start a run"
        config = sub('\.xml$', '', config)
        self.__rpc.rpc_start_run(r, 0, config, logInfo)
        return DAQRunIface.START_TRANSITION_SECONDS
    
    def stop(self):
        "Tell DAQRun to stop a run"
        self.__rpc.rpc_stop_run()
        return DAQRunIface.STOP_TRANSITION_SECONDS
    
    def recover(self):
        "Tell DAQRun to recover from an error and go to STOPPED state"
        self.__rpc.rpc_recover()
        return DAQRunIface.RECOVERY_TRANSITION_SECONDS
    
    def getState(self):
        "Get current DAQ state"
        return self.__rpc.rpc_run_state()

    def flasher(self, subRunID, flashingDomsList):
        """
        Tell DAQ to flash DOMs.  subRunID is 0, 1, ....  flashingDomsList is a list of
        tuples in the form (domid,       brightness, window, delay, mask, rate)
        or                 (dom_name,    "                                   ")
        or                 (string, pos, "                                   ")
        or a list of dictionaries, one per DOM, whose keys are
            'stringHub','domPosition','brightness','window','delay','mask','rate'
            and whose values are strings.
            (THIS OPTION WILL RAISE A KEYERROR IF YOU DON'T PASS THE CORRECT ARGS)
        Return value is 1 if the operation succeeded (subrun successfully started),
        else 0 (in which case, check the pDAQ logs for diagnostic information).
        
        """
        if flashingDomsList == []: pass # Nothing to do except stop the subrun
        elif type(flashingDomsList[0]) == DictType: # Check for dictionary list signature
            l = []
            # Throws exception if dictionary is messed up:
            try:
                for dom in flashingDomsList:
                    if dom.has_key('stringHub') and dom.has_key('domPosition'):
                        l.append((int(dom['stringHub']),
                                  int(dom['domPosition']),
                                  int(dom['brightness']),
                                  int(dom['window']),
                                  int(dom['delay']),
                                  int(dom['mask'], 16),
                                  int(dom['rate'])))
                    elif dom.has_key('MBID'):
                        l.append((str(dom['MBID']),
                                  int(dom['brightness']),
                                  int(dom['window']),
                                  int(dom['delay']),
                                  int(dom['mask'], 16),
                                  int(dom['rate'])))
                    else: raise MalformedFlasherInput('Hash error on input')
            except Exception, e:
                m = 'Input was: '+str(flashingDomsList)
                if not e.args: e.args = [ m, ]
                else:
                    e.args = (e.args[0], m) + e.args[1:]
                raise

            flashingDomsList = l

        #print "Subrun %d: DOMs to flash: %s" % (subRunID, str(flashingDomsList))
        return self.__rpc.rpc_flash(subRunID, flashingDomsList)
    
    def getSummary(self):
        "Get component summary from DAQRun"
        return self.__rpc.rpc_daq_summary_xml()
    
    def release(self):
        """
        Release DAQ component resources (run sets) back to CnC Server
        Use for "standalone" instances of DAQ (i.e. non-'Experiment Control')
        """
        self.__rpc.rpc_release_runsets()
        return DAQRunIface.RELEASE_TRANSITION_SECONDS
    
    def getDaqLabels(self):        
        parser = DAQLabelParser(join(self.__home, "dash", "config",
                                     "daqlabels.xml"))
        return parser.dict, parser.defaultLabel

    def isValidConfig(self, configName):
        "Placeholder only until this is implemented"
        configDir = join(self.__home, "config")
        return DAQConfig.configExists(configName, configDir)
    
    def monitorRun(self):
        "Get run monitoring data"
        return self.__rpc.rpc_run_monitoring()

    def checkID(self):
        if self.__id is None:
            self.__id = self.__rpc.rpc_ping()
            return True

        newID = self.__rpc.rpc_ping()
        unchanged = self.__id == newID
        self.__id = newID
        return unchanged

if __name__ == "__main__":
    iface = DAQRunIface()
    print iface.getDaqLabels()
