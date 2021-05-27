#!/usr/bin/env python
"""
"header" file which defines all important internally used socket ports
"""

class DAQPort(object):
    "DAQLive port"
    DAQLIVE = 6659
    "IceCube Live logging port"
    I3LIVE = 6666
    "IceCube Live ZMQ logging port"
    I3LIVE_ZMQ = 6668
    "CnCServer XML-RPC port"
    CNCSERVER = 8080
    "CnCServer->DAQRun logging port"
    CNC2RUNLOG = 8999
    "DAQRun XML-RPC port"
    DAQRUN = 9000
    "DAQRun catchall logging port"
    CATCHALL = 9001
    "First ephemeral socket port"
    EPHEMERAL_BASE = 49152
    "First ephemeral socket port"
    EPHEMERAL_MAX = 65535
