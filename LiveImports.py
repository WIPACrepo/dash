#!/usr/bin/env python

try:
    try:
        from live.transport.moniclient import DefaultMoniClient as MoniClient
        from live.transport.moniclient import default_moni_port as MoniPort
    except ImportError:
        from live.control.LiveMoni import MoniClient
        MoniPort = 6666

    from live.control.component import Component as LiveComponent
    try:
        from live.control.component import INCOMPLETE_STATE_CHANGE
    except ImportError:
        INCOMPLETE_STATE_CHANGE = None

    try:
        from live.transport.priorities import Prio
    except ImportError:
        try:
            from live.transport.prioqueue import Prio
        except ImportError:
            from live.transport.Queue import Prio

    # set pDAQ's I3Live service name
    SERVICE_NAME = "pdaq"

    # indicate that import succeeded
    LIVE_IMPORT = True
except ImportError:
    # create bogus placeholder classes
    class LiveComponent(object):
        def __init__(self, compName, rpcPort=None, moniHost=None,
                     moniPort=None, synchronous=None, lightSensitive=None,
                     makesLight=None, logger=None):
            pass

        def close(self):
            pass

        def run(self):
            pass

    class Prio(object):
        ITS = 123
        EMAIL = 444
        SCP = 555
        DEBUG = 666

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

    MoniPort = 6666

    # set bogus service name
    SERVICE_NAME = "pdaqFake"

    # Sginal that we're using the old API
    INCOMPLETE_STATE_CHANGE = None

    # indicate that import failed
    LIVE_IMPORT = False

if __name__ == "__main__":
    pass
