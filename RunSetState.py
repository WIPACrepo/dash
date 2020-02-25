#!/usr/bin/env python


class RunSetState(object):
    """
    These strings should match the state names in
    icecube.daq.juggler.component.DAQComponent
    """
    UNKNOWN = "unknown"
    IDLE = "idle"
    CONFIGURING = "configuring"
    CONNECTED = "connected"
    CONNECTING = "connecting"
    INIT_REPLAY = "initializingReplay"
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FORCING_STOP = "forcingStop"
    DESTROYED = "destroyed"
    RESETTING = "resetting"
    # ERROR is not defined in DAQComponent
    ERROR = "error"
