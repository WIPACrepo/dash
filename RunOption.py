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

    @staticmethod
    def __appendWithComma(prevstr, addstr):
        if prevstr is None:
            return addstr
        return prevstr + "," + addstr

    @staticmethod
    def __isOption(flags, option):
        return (flags & option) == option

    @staticmethod
    def isLogToBoth(flags):
        return RunOption.__isOption(flags, RunOption.LOG_TO_FILE | RunOption.LOG_TO_LIVE)
    
    @staticmethod
    def isLogToFile(flags):
        return RunOption.__isOption(flags, RunOption.LOG_TO_FILE)
    
    @staticmethod
    def isLogToLive(flags):
        return RunOption.__isOption(flags, RunOption.LOG_TO_LIVE)

    @staticmethod
    def isLogToNone(flags):
        return RunOption.__isOption(flags, RunOption.LOG_TO_NONE)
    
    @staticmethod
    def isMoniToBoth(flags):
        return RunOption.__isOption(flags, RunOption.MONI_TO_FILE | RunOption.MONI_TO_LIVE)

    @staticmethod
    def isMoniToFile(flags):
        return RunOption.__isOption(flags, RunOption.MONI_TO_FILE)

    @staticmethod
    def isMoniToLive(flags):
        return RunOption.__isOption(flags, RunOption.MONI_TO_LIVE)

    @staticmethod
    def isMoniToNone(flags):
        return RunOption.__isOption(flags, RunOption.MONI_TO_NONE)

    @staticmethod
    def string(flags):
        logStr = None
        if RunOption.isLogToNone(flags):
            logStr = RunOption.__appendWithComma(logStr, "None")
        if RunOption.isLogToBoth(flags):
            logStr = RunOption.__appendWithComma(logStr, "Both")
        elif RunOption.isLogToFile(flags):
            logStr = RunOption.__appendWithComma(logStr, "File")
        elif RunOption.isLogToLive(flags):
            logStr = RunOption.__appendWithComma(logStr, "Live")
        elif logStr is None:
            logStr = ""

        moniStr = None
        if RunOption.isMoniToNone(flags):
            moniStr = RunOption.__appendWithComma(moniStr, "None")
        if RunOption.isMoniToBoth(flags):
            moniStr = RunOption.__appendWithComma(moniStr, "Both")
        elif RunOption.isMoniToFile(flags):
            moniStr = RunOption.__appendWithComma(moniStr, "File")
        elif RunOption.isMoniToLive(flags):
            moniStr = RunOption.__appendWithComma(moniStr, "Live")
        elif moniStr is None:
            moniStr = ""

        return "RunOption[log(%s)moni(%s)]" % (logStr, moniStr)

