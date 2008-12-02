#!/usr/bin/env python

#
# DAQ Constant values

class DAQPort(object):
    "IceCube Live logging/monitoring port"
    I3LIVE       = 6666
    "CnCServer XML-RPC port"
    CNCSERVER    = 8080
    "CnCServer->DAQRun logging port"
    CNC2RUNLOG   = 8999
    "DAQRun XML-RPC port"
    DAQRUN       = 9000
    "DAQRun catchall logging port"
    CATCHALL     = 9001
    "First port used by DAQRun for individual component logging"
    RUNCOMP_BASE = 9002
