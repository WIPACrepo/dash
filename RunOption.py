#!/usr/bin/env python

class RunOption(object):
    LOG_TO_NONE = 0x1
    LOG_TO_FILE = 0x2
    LOG_TO_LIVE = 0x4
    LOG_TO_BOTH = LOG_TO_FILE | LOG_TO_LIVE
    MONI_TO_NONE = 0x1000
    MONI_TO_FILE = 0x2000
    MONI_TO_LIVE = 0x4000
    MONI_TO_BOTH = MONI_TO_FILE | MONI_TO_LIVE

    def __isOption(cls, flags, option):
        return (flags & option) == option
    __isOption = classmethod(__isOption)

    def isLogToBoth(cls, flags):
        return cls.__isOption(flags, cls.LOG_TO_FILE | cls.LOG_TO_LIVE)
    isLogToBoth = classmethod(isLogToBoth)

    def isLogToFile(cls, flags):
        return cls.__isOption(flags, cls.LOG_TO_FILE)
    isLogToFile = classmethod(isLogToFile)

    def isLogToLive(cls, flags):
        return cls.__isOption(flags, cls.LOG_TO_LIVE)
    isLogToLive = classmethod(isLogToLive)

    def isLogToNone(cls, flags):
        return cls.__isOption(flags, cls.LOG_TO_NONE)
    isLogToNone = classmethod(isLogToNone)

    def isMoniToBoth(cls, flags):
        return cls.__isOption(flags, cls.MONI_TO_FILE | cls.MONI_TO_LIVE)
    isMoniToBoth = classmethod(isMoniToBoth)

    def isMoniToFile(cls, flags):
        return cls.__isOption(flags, cls.MONI_TO_FILE)
    isMoniToFile = classmethod(isMoniToFile)

    def isMoniToLive(cls, flags):
        return cls.__isOption(flags, cls.MONI_TO_LIVE)
    isMoniToLive = classmethod(isMoniToLive)

    def isMoniToNone(cls, flags):
        return cls.__isOption(flags, cls.MONI_TO_NONE)
    isMoniToNone = classmethod(isMoniToNone)
