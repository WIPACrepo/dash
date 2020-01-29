#!/usr/bin/env python

# assume that the imports will succeed
LIVE_IMPORT = True

# attempt to import MoniClient 
try:
    from live.transport.moniclient import DefaultMoniClient as MoniClient
except ImportError:
    try:
        from live.control.LiveMoni import MoniClient
    except ImportError:
        LIVE_IMPORT = False
        class MoniClient(object):
            def __init__(self, service, host, port, logger=None):
                pass

            def __str__(self):
                """
                The returned string should start with "BOGUS"
                so DAQRun can detect problems
                """
                return "BOGUS"

            def close(self):
                pass

            def sendMoni(self, name, data, prio=None, time=None):
                pass

# attempt to import MoniPort
try:
    from live.transport.moniclient import default_moni_port as MoniPort
except ImportError:
    LIVE_IMPORT = False
    MoniPort = 6666

# attempt to import LiveComponent
try:
    from live.control.component import Component as LiveComponent
except ImportError:
    LIVE_IMPORT = False
    class LiveComponent(object):
        def __init__(self, compName, rpcPort=None, moniHost=None,
                     moniPort=None, synchronous=None, lightSensitive=None,
                     makesLight=None, logger=None):
            pass

        def close(self):
            pass

        def run(self):
            pass

# attempt to import INCOMPLETE_STATE_CHANGE
try:
    from live.control.component import INCOMPLETE_STATE_CHANGE
except ImportError:
    LIVE_IMPORT = False
    INCOMPLETE_STATE_CHANGE = None

# attempt to import Prio
try:
    from live.transport.priorities import Prio
except ImportError:
    try:
        from live.transport.prioqueue import Prio
    except ImportError:
        try:
            from live.transport.Queue import Prio
        except ImportError:
            LIVE_IMPORT = False
            class Prio(object):
                ITS = 123
                EMAIL = 444
                SCP = 555
                DEBUG = 666

# set pDAQ's I3Live service name
if LIVE_IMPORT:
    SERVICE_NAME = "pdaq"
else:
    SERVICE_NAME = "pdaqFake"


if __name__ == "__main__":
    pass
