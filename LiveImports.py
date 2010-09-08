#!/usr/bin/env python

try:
    from live.control.LiveMoni import MoniClient
    from live.control.component import Component
    from live.control.log \
        import LOG_FATAL, LOG_ERROR, LOG_WARN, LOG_INFO, LOG_DEBUG, LOG_TRACE
    from live.transport.Queue import Prio

    # set pDAQ's I3Live service name
    SERVICE_NAME = "pdaq"

    # indicate that import succeeded
    LIVE_IMPORT = True
except ImportError:
    # create bogus placeholder classes
    class Component(object):
        def __init__(self, compName, rpcPort=None, moniHost=None,
                     moniPort=None, synchronous=None, lightSensitive=None,
                     makesLight=None, logger=None):
            pass

        def close(self): pass

    class Prio(object):
        ITS   = 123
        EMAIL = 444
        SCP   = 555
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

    # set bogus log level constants
    LOG_FATAL = 32760
    LOG_ERROR = LOG_FATAL + 1
    LOG_WARN = LOG_ERROR + 1
    LOG_INFO = LOG_WARN + 1
    LOG_DEBUG = LOG_INFO + 1
    LOG_TRACE = LOG_DEBUG + 1

    # set bogus service name
    SERVICE_NAME = "unimported"

    # indicate that import failed
    LIVE_IMPORT = False

if __name__ == "__main__": pass
