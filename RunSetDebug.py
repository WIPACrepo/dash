#!/usr/bin/env python

class RunSetDebug(object):
    ACTDOM_TASK = 0x1
    MONI_TASK = 0x2
    RADAR_TASK = 0x4
    RATE_TASK = 0x8
    WATCH_TASK = 0x10

    START_RUN = 0x100
    STOP_RUN = 0x200

    ALL = ACTDOM_TASK | MONI_TASK | RADAR_TASK | RATE_TASK | WATCH_TASK | \
          START_RUN | STOP_RUN

    NAME_MAP = {
        "activeDomsTask" : ACTDOM_TASK,
        "moniTask" : MONI_TASK,
        "radarTask" : RADAR_TASK,
        "rateTask" : RATE_TASK,
        "watchdogTask" : WATCH_TASK,
        "startRun" : START_RUN,
        "stopRun" : STOP_RUN,
        "all" : ALL,
        }
