#!/usr/bin/env python


class RunOption(object):
    "Run options"

    LOG_TO_NONE = 0x1
    LOG_TO_FILE = 0x2
    LOG_TO_LIVE = 0x4
    LOG_TO_BOTH = LOG_TO_FILE | LOG_TO_LIVE
    MONI_TO_NONE = 0x1000
    MONI_TO_FILE = 0x2000
    MONI_TO_LIVE = 0x4000
    MONI_TO_BOTH = MONI_TO_FILE | MONI_TO_LIVE

    @staticmethod
    def __append_with_comma(prevstr, addstr):
        """
        if the previous string is None, return the new string
        if the previous string contains characters,
        append a comma followed by the new string
        """
        if prevstr is None:
            return addstr
        return prevstr + "," + addstr

    @staticmethod
    def __is_option(flags, option):
        "Return True if the 'option' bit is set in 'flags'"
        return (flags & option) == option

    @staticmethod
    def is_log_to_both(flags):
        "Return True if log messages should be sent to both Live and a file"
        return RunOption.__is_option(flags, (RunOption.LOG_TO_FILE |
                                             RunOption.LOG_TO_LIVE))

    @staticmethod
    def is_log_to_file(flags):
        "Return True if log messages should be written to a local file"
        return RunOption.__is_option(flags, RunOption.LOG_TO_FILE)

    @staticmethod
    def is_log_to_live(flags):
        "Return True if log messages should be sent to Live"
        return RunOption.__is_option(flags, RunOption.LOG_TO_LIVE)

    @staticmethod
    def is_log_to_none(flags):
        "Return True if logging is disabled"
        return RunOption.__is_option(flags, RunOption.LOG_TO_NONE)

    @staticmethod
    def is_moni_to_both(flags):
        "Return True if monitoring should be sent to both Live and a file"
        return RunOption.__is_option(flags, (RunOption.MONI_TO_FILE |
                                             RunOption.MONI_TO_LIVE))

    @staticmethod
    def is_moni_to_file(flags):
        "Return True if monitoring should be written to a local file"
        return RunOption.__is_option(flags, RunOption.MONI_TO_FILE)

    @staticmethod
    def is_moni_to_live(flags):
        "Return True if monitoring should be sent to both pDAQ and Live"
        return RunOption.__is_option(flags, RunOption.MONI_TO_LIVE)

    @staticmethod
    def is_moni_to_none(flags):
        "Return True if monitoring is disabled"
        return RunOption.__is_option(flags, RunOption.MONI_TO_NONE)

    @staticmethod
    def string(flags):
        "Return a string description of the options"
        logstr = None
        if RunOption.is_log_to_none(flags):
            logstr = RunOption.__append_with_comma(logstr, "None")
        if RunOption.is_log_to_both(flags):
            logstr = RunOption.__append_with_comma(logstr, "Both")
        elif RunOption.is_log_to_file(flags):
            logstr = RunOption.__append_with_comma(logstr, "File")
        elif RunOption.is_log_to_live(flags):
            logstr = RunOption.__append_with_comma(logstr, "Live")
        elif logstr is None:
            logstr = ""

        monistr = None
        if RunOption.is_moni_to_none(flags):
            monistr = RunOption.__append_with_comma(monistr, "None")
        if RunOption.is_moni_to_both(flags):
            monistr = RunOption.__append_with_comma(monistr, "Both")
        elif RunOption.is_moni_to_file(flags):
            monistr = RunOption.__append_with_comma(monistr, "File")
        elif RunOption.is_moni_to_live(flags):
            monistr = RunOption.__append_with_comma(monistr, "Live")
        elif monistr is None:
            monistr = ""

        return "RunOption[log(%s)moni(%s)]" % (logstr, monistr)
