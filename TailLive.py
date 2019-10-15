#!/usr/bin/env python
#
# Add color to `livecmd tail` output so it's more readable

from __future__ import print_function

import ast
import datetime
import os
import re
import subprocess
import sys
import threading
import Queue

from ANSIEscapeCode import ANSIEscapeCode, background_color, foreground_color
from ColorFileParser import ColorException, ColorFileParser


def add_arguments(parser):
    parser.add_argument("-A", "--all-logs", dest="all_logs",
                        action="store_true", default=False,
                        help=("Read all log files instead of 'tail'ing"
                              " the most recent"))
    parser.add_argument("-a", "--all", dest="all_data",
                        action="store_true", default=False,
                        help="Show all data")
    parser.add_argument("-C", "--color-file", dest="color_file",
                        help="File specifying non-standard colors")
    parser.add_argument("-L", "--non-log-messages", dest="non_log",
                        action="store_true", default=False,
                        help="Print alerts and monitoring messages")
    parser.add_argument("-l", "--tailLines", type=int, dest="tail_lines",
                        action="store", default=100,
                        help=("Number of previous lines initially shown"
                              " by 'tail'"))
    parser.add_argument("-p", "--pdaq-only", dest="pdaq_only",
                        action="store_true", default=False,
                        help="Only print pdaq log messages")
    parser.add_argument("-q", "--quiet", dest="quiet",
                        action="store_true", default=False,
                        help="Omit some noisy pdaq log messages")
    parser.add_argument("--print-colors", dest="print_colors",
                        action="store_true", default=False,
                        help="Print a formatted list of fields and colors")
    parser.add_argument("files", nargs="*")


def tail_logs(args):
    if args.print_colors:
        try:
            ColorFileParser(args.color_file).parse(LiveLog.COLORS)
        except ColorException as cex:
            raise SystemExit(str(cex))

        ColorFileParser.print_formatted(LiveLog.COLORS)
        return

    # get list of files to watch
    if len(args.files) > 0:
        if len(args.files) == 1:
            log = Tail(args.files[0], num_lines=args.tail_lines)
        else:
            log = AllFiles(args.files)
    elif args.all_logs:
        log = AllLogs()
    else:
        log = Tail(num_lines=args.tail_lines)

    llog = LiveLog(log, show_all=args.all_data, pdaq_only=args.pdaq_only,
                   non_log=args.non_log, quiet=args.quiet,
                   color_file=args.color_file)
    llog.read_file()


class LiveLogException(Exception):
    pass


class LiveData(object):
    TYPE_LOG = 1
    TYPE_MONI = 2
    TYPE_MSGDICT = 3
    TYPE_ALERT = 4
    TYPE_MSGERR = 5
    TYPE_WARN = 6
    TYPE_MSGLIST = 7
    TYPE_UNKNOWN = 99

    def __init__(self, dtype):
        self.__datatype = dtype

    @property
    def datatype(self):
        return self.__datatype

    @property
    def data(self):
        raise NotImplementedError()

    @property
    def is_dict(self):
        return False

    @property
    def is_list(self):
        return False

    @property
    def is_text(self):
        return False

    @property
    def typestring(self):
        if self.__datatype == self.TYPE_LOG:
            return "LOG"
        if self.__datatype == self.TYPE_MONI:
            return "MONI"
        if self.__datatype == self.TYPE_MSGDICT:
            return "MSGDICT"
        if self.__datatype == self.TYPE_ALERT:
            return "ALERT"
        if self.__datatype == self.TYPE_MSGERR:
            return "MSGERR"
        if self.__datatype == self.TYPE_WARN:
            return "WARN"
        if self.__datatype == self.TYPE_UNKNOWN:
            return "UNKNOWN"
        return "??%d??" % (self.__datatype, )


class TextData(LiveData):
    def __init__(self, dtype, text):
        self.__text = text

        super(TextData, self).__init__(dtype)

    def __str__(self):
        return "[%s] %s" % (self.typestring, self.__text)

    @property
    def is_text(self):
        return True

    @property
    def data(self):
        return self.__text


class DictData(LiveData):
    def __init__(self, dtype, ddict):
        self.__dict = ddict

        super(DictData, self).__init__(dtype)

    def __str__(self):
        return "[%s] %s" % (self.typestring, self.__dict)

    @property
    def is_dict(self):
        return True

    @property
    def data(self):
        return self.__dict


class ListData(LiveData):
    def __init__(self, dtype, dlist):
        self.__list = dlist

        super(ListData, self).__init__(dtype)

    def __str__(self):
        return "[%s] %s" % (self.typestring, self.__list)

    @property
    def is_list(self):
        return True

    @property
    def data(self):
        return self.__list


class LiveLine(object):
    PREFIX_PAT = re.compile(r"^\s+live(?:control|cmd)\((\S+)\)" +
                            r"\s+(\d+-\d+-\d+ \d+:\d+:\d+,\d+)\s+(.*)$",
                            re.DOTALL)
    TIME_FMT = "%Y-%m-%d %H:%M:%S,%f"

    OLDLOG_PAT = re.compile(r"(\S+)\(([^\)\:]+)\:([^\)]+)\)\s+(\d+)"
                            r" \[(\d+-\d+-\d+ \d+:\d+:\d+)(\.\d+)?\]\s+(.*)")

    def __init__(self, line):
        match = self.PREFIX_PAT.match(line)
        if match is None:
            raise LiveLogException("Bad line: " + line.rstrip())

        self.__msgtype = match.group(1)
        self.__timestamp = datetime.datetime.strptime(match.group(2),
                                                      self.TIME_FMT)
        self.__data = self.__parse_data(match.group(3))

    def __str__(self):
        return "[%s]%s %s" % (self.__msgtype, self.__timestamp, self.__data)

    @classmethod
    def __parse_datetime_dict(cls, astr, debug=False):
        try:
            tree = ast.parse(astr)
        except SyntaxError:
            raise ValueError(astr)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.Expr, ast.Dict, ast.Str,
                                 ast.List, ast.Attribute, ast.Num, ast.Name,
                                 ast.Load)):
                continue
            if isinstance(node, ast.Call) and \
               isinstance(node.func, ast.Attribute) and \
               node.func.attr == 'datetime':
                continue
            if debug:
                attrs = [attr for attr in dir(node)
                         if not attr.startswith('__')]
                print(node, file=sys.stderr)
                for attrname in attrs:
                    print('    %s ==> %s' % \
                        (attrname, getattr(node, attrname)), file=sys.stderr)
            raise ValueError(astr)

        return eval(astr)

    @classmethod
    def __parse_data(cls, line, debug=False):
        if line.startswith("--- ") or line.startswith("... "):
            match = cls.OLDLOG_PAT.match(line[4:])
            if match is not None:
                prio = int(match.group(4))
                dtstr = match.group(5)
                if match.group(6) is not None:
                    dtstr += match.group(6)

                endidx = match.end() + 4
                if endidx >= len(line):
                    value = match.group(7)
                else:
                    value = match.group(7) + line[endidx:]

                payload = {
                    "service": match.group(1),
                    "varname": match.group(2),
                    "prio": prio,
                    "time": dtstr,
                    "value": value,
                }
                return DictData(LiveData.TYPE_LOG, cls.__wrap_payload(payload))

        if line.startswith("Got user-generated alert message: \"") and \
          line.endswith("\""):
            try:
                ddict = cls.__parse_datetime_dict(line[35:-1], debug=debug)
                if "varname" in ddict:
                    ddict = cls.__wrap_payload(ddict)
                return DictData(LiveData.TYPE_ALERT, ddict)
            except:
                import traceback; traceback.print_exc()
                pass

        if line.startswith("WARN_MONI_SEND: "):
            try:
                ddict = cls.__parse_datetime_dict(line[16:], debug=debug)
                return DictData(LiveData.TYPE_MONI, ddict)
            except:
                pass

        if line.startswith("{") and line.endswith("}"):
            try:
                ddict = cls.__parse_datetime_dict(line, debug=debug)
                return DictData(LiveData.TYPE_MSGDICT, ddict)
            except:
                pass

        if line.startswith("[") and line.endswith("]"):
            try:
                dlist = cls.__parse_datetime_dict(line, debug=debug)
                return ListData(LiveData.TYPE_MSGLIST, dlist)
            except:
                pass

        if line.startswith("Message error: "):
            return TextData(TextData.TYPE_MSGERR, line[15:])

        if line.startswith("Warning: "):
            return TextData(TextData.TYPE_WARN, line[9:])

        return TextData(TextData.TYPE_UNKNOWN, line)

    @classmethod
    def __wrap_payload(cls, payload):
        if "t" in payload and "payload" in payload:
            return payload

        if "service" in payload:
            svc = payload["service"]
        else:
            svc = "unknown"

        if "prio" in payload:
            prio = int(payload["prio"])
        else:
            prio = -1

        if "t" in payload:
            ptime = payload["t"]
        elif "time" not in payload:
            ptime = None
        elif isinstance(payload["time"], datetime.datetime):
            ptime = payload["time"]
        else:
            dtstr = payload["time"]
            try:
                ptime = datetime.datetime.strptime(dtstr,
                                                   "%Y-%m-%d %H:%M:%S.%f")
            except:
                try:
                    ptime = datetime.datetime.strptime(dtstr,
                                                       "%Y-%m-%d %H:%M:%S")
                except:
                    ptime = None
        if ptime is None:
            ptime = datetime.datetime(2000, 1, 1, 0, 0, 0, 0)

        return {
            "service": svc,
            "prio": prio,
            "t": ptime,
            "payload": payload
        }

    @property
    def data(self):
        return self.__data

    @property
    def msgtype(self):
        return self.__msgtype

    @property
    def timestamp(self):
        return self.__timestamp


class LiveFile(object):
    def __init__(self):
        self.__basepath = None

    def basepath(self):
        if self.__basepath is None:
            self.__basepath = os.path.join(os.environ["HOME"], ".i3live.log")
        return self.__basepath


class Tail(LiveFile):
    def __init__(self, filename=None, num_lines=None):
        self.__proc = None

        super(Tail, self).__init__()

        if filename is None:
            filename = self.basepath()
        if not os.path.exists(filename):
            raise ValueError("File \"%s\" does not exist" % filename)

        self.__num_lines = num_lines
        self.__queue = Queue.Queue(maxsize=100)
        self.__thread = threading.Thread(target=self.__run, args=(filename, ))
        self.start()

    def __iter__(self):
        return self

    def __run(self, filename):
        """Run tail forever"""
        args = ["tail", "-F"]
        if self.__num_lines is not None and self.__num_lines > 0:
            args.append("-n")
            args.append(str(self.__num_lines))
        args.append(filename)

        self.__proc = subprocess.Popen(args, stdout=subprocess.PIPE)
        while True:
            line = self.__proc.stdout.readline()
            self.__queue.put(line)
            if not line:
                break

    def __next__(self):
        return self.readline()

    def close(self):
        self.__proc.kill()

    next = __next__ # XXX backward compatibility for Python 2

    def readline_nb(self):
        """Non-blocking read"""
        return self.__queue.get_nowait()

    def readline(self):
        """Blocking read"""
        return self.__queue.get()

    def start(self):
        """Start the tail subprocess"""
        self.__thread.start()


class MultiFile(LiveFile):
    def __init__(self):
        self.__logname = None
        self.__fd = None

        super(MultiFile, self).__init__()

    def __iter__(self):
        return self

    def __next__(self):
        return self.readline()

    def next_file(self):
        raise NotImplementedError()

    def close(self):
        self.__fd.close()

    next = __next__ # XXX backward compatibility for Python 2

    def readline(self):
        while True:
            if self.__fd is None:
                self.__logname = self.next_file()
                if self.__logname is None:
                    break
                self.__fd = open(self.__logname, "r")

            line = self.__fd.readline()
            if line != "":
                return line

            self.__fd.close()
            self.__fd = None


class AllFiles(MultiFile):
    def __init__(self, file_list):
        self.__file_list = file_list

        super(AllFiles, self).__init__()

    def next_file(self):
        while len(self.__file_list) > 0:
            path = self.__file_list.pop(0)
            if os.path.exists(path):
                return path
            print("File \"%s\" does not exist" % path, file=sys.stderr)


class AllLogs(MultiFile):
    def __init__(self):
        self.__next_num = 0

        super(AllLogs, self).__init__()

    def next_file(self):
        if self.__next_num == 0:
            suffix = ""
        else:
            suffix = ".%d" % self.__next_num
        self.__next_num += 1

        path = self.basepath() + suffix
        if not os.path.exists(path):
            return None

        return path


class LiveLog(object):
    # if the output isn't a terminal, don't add ANSI escapes
    TTYOUT = sys.stdout.isatty()

    FIELD_CHAT = "chat"
    FIELD_ITS = "its"
    FIELD_LIVE_MISC = "live_misc"
    FIELD_LIVECONTROL = "livecontrol"
    FIELD_PDAQ_HEALTH = "pdaq_health"
    FIELD_PDAQ_INFO = "pdaq_info"
    FIELD_PDAQ_LOAD = "pdaq_load"
    FIELD_PDAQ_MISC = "pdaq_misc"
    FIELD_PDAQ_OTHER = "pdaq_other"
    FIELD_PDAQ_RATE = "pdaq_rate"
    FIELD_PDAQ_REGISTERED = "pdaq_registered"
    FIELD_PDAQ_WAIT = "pdaq_wait"
    FIELD_PDAQ_WATCHDOG = "pdaq_watchdog"
    FIELD_SNDAQ = "sndaq"
    FIELD_UNFORMATTED = "unformatted"
    FIELD_UNKNOWN = "unknown"

    # predefined fields and colors
    COLORS = {
        ColorFileParser.DEFAULT_FIELD: (ANSIEscapeCode.RED,
                                        ANSIEscapeCode.YELLOW),
        FIELD_CHAT: (ANSIEscapeCode.MAGENTA, ANSIEscapeCode.WHITE,
                     ANSIEscapeCode.BOLD_ON),
        FIELD_ITS: None,
        FIELD_LIVECONTROL: (),
        FIELD_LIVE_MISC: (ANSIEscapeCode.YELLOW, ANSIEscapeCode.BLACK),
        FIELD_PDAQ_HEALTH: (ANSIEscapeCode.GREEN, ANSIEscapeCode.BLACK),
        FIELD_PDAQ_INFO: (ANSIEscapeCode.BLUE, ANSIEscapeCode.WHITE),
        FIELD_PDAQ_LOAD: (),
        FIELD_PDAQ_RATE: (ANSIEscapeCode.GREEN, ANSIEscapeCode.WHITE),
        FIELD_PDAQ_REGISTERED: (),
        FIELD_PDAQ_WAIT: (ANSIEscapeCode.MAGENTA, ANSIEscapeCode.WHITE),
        FIELD_PDAQ_WATCHDOG: (ANSIEscapeCode.RED, ANSIEscapeCode.WHITE),
        FIELD_SNDAQ: (ANSIEscapeCode.BLUE, ANSIEscapeCode.YELLOW),
        FIELD_UNFORMATTED: (ANSIEscapeCode.RED, ANSIEscapeCode.YELLOW,
                            ANSIEscapeCode.ITALIC_ON),
        FIELD_UNKNOWN: (ANSIEscapeCode.RED, ANSIEscapeCode.YELLOW,
                        ANSIEscapeCode.BOLD_ON),
    }

    def __init__(self, fd, show_all=False, pdaq_only=False, non_log=False,
                 quiet=False, color_file=None):
        self.__fd = fd
        self.__show_all = show_all
        self.__pdaq_only = pdaq_only
        self.__non_log = non_log
        self.__quiet = quiet

        # get customized colors
        try:
            ColorFileParser(color_file).parse(self.COLORS)
        except ColorException as cex:
            raise SystemExit(str(cex))

        super(LiveLog, self).__init__()

    def __color_log(self, date, msg):
        if msg.find("ShutdownHook") > 0:
            return None

        if msg.find(" physics events") > 0 and \
                msg.find(" moni events") > 0:
            # rate line
            return self.string(self.FIELD_PDAQ_RATE, date, msg)

        if msg.startswith("Registered "):
            # registered
            if self.__quiet:
                return None
            return self.string(self.FIELD_PDAQ_REGISTERED, date, msg)

        if msg.startswith("Waiting for ") or \
                (msg.startswith("RunSet #") and
                 msg.find("Waiting for ")):
            # waiting for
            return self.string(self.FIELD_PDAQ_WAIT, date, msg)

        if msg.startswith("Loading run configuration ") or \
                msg.startswith("Loaded run configuration "):
            # run config
            return self.string(self.FIELD_PDAQ_LOAD, date, msg)

        if msg.startswith("Starting run ") or \
                msg.startswith("Version info: ") or \
                msg.startswith("Run configuration: ") or \
                msg.startswith("Cluster: "):
            # run start
            return self.string(self.FIELD_PDAQ_INFO, date, msg)

        if msg.find(" physics events collected in ") > 0 or \
                msg.find(" moni events, ") > 0 or \
                msg.startswith("Run terminated "):
            # run end
            return self.string(self.FIELD_PDAQ_INFO, date, msg)

        if msg.startswith("Cycling components") or \
                msg.startswith("Built runset #"):
            # cycle components
            return self.string(self.FIELD_PDAQ_MISC, date, msg)

        if msg.startswith("Run is healthy again"):
            # whew
            return self.string(self.FIELD_PDAQ_HEALTH, date, msg)

        if msg.startswith("Watchdog reports"):
            # whew
            return self.string(self.FIELD_PDAQ_WATCHDOG, date, msg)

        return self.string(self.FIELD_PDAQ_OTHER, date, msg)

    def __process_control(self, line):
        "Handle a (possibly incomplete) Live log message"
        liveline = LiveLine(line)

        data = liveline.data
        if data.is_text:
            self.__process_livetext(liveline.timestamp, data.data)
            return

        if data.is_list:
            for entry in data.data:
                self.__process_message(entry, default_time=liveline.timestamp)
            return

        if data.is_dict:
            self.__process_message(data.data, default_time=liveline.timestamp)
            return

        line = self.string(self.FIELD_UNKNOWN, liveline.timestamp,
                           str(data.data))
        print(line)
        return

    def __process_livetext(self, timestamp, msg):
        "Handle Live text messages"
        field = self.FIELD_UNKNOWN
        if msg.find("flowed max message size in queue ITSQueue") > 0 or \
          msg.startswith("Sent ITS Message: "):
            field = self.FIELD_ITS
        elif msg.find("unable to send message") >= 0 and \
          msg.find("in queue ITSQueue!!!") > 0:
            field = self.FIELD_ITS
        elif msg.find("Sent 'chat' message") >= 0 or \
          msg.find("Got message list from ") >= 0:
            # silence some noise around Slack messages
            if self.__show_all:
                field = self.FIELD_ITS
            else:
                field = None
        else:
            no_svc_str = "Unable to retrieve status for service "

            svcidx = msg.find(no_svc_str)
            if svcidx >= 0:
                if self.__show_all:
                    field = self.FIELD_LIVECONTROL
                else:
                    offset = svcidx + len(no_svc_str)
                    final = msg.find(":", offset)
                    if final > 0:
                        msg = "Cannot retrieve status from " + msg[offset:final]
                        field = self.FIELD_LIVECONTROL

        if field is not None:
            line = self.string(field, timestamp, msg)
            print(line)

    def __process_message(self, ddict, default_time=None):
        "Process a Live JSON message"
        if "service" not in ddict:
            line = self.string(self.FIELD_UNKNOWN, default_time,
                               str(ddict))
            print(line)
            return

        svc = ddict["service"]
        if "t" not in ddict or "payload" not in ddict or \
          not isinstance(ddict["payload"], dict):
            line = self.string(self.FIELD_UNFORMATTED, default_time,
                               "??? " + str(ddict))
            print(line)
            return

        payload = ddict["payload"]
        if "varname" not in payload:
            if svc == "SlackForwarder":
                if "user" in payload and "message" in payload:
                    line = self.string(self.FIELD_CHAT, ddict["t"],
                                       "%s:: %s" % (payload["user"],
                                                    payload["message"]))
                    print(line)
                    return

            if self.__show_all:
                if svc == "livecontrol":
                    fldtype = self.FIELD_LIVECONTROL
                else:
                    fldtype = self.FIELD_UNFORMATTED
                line = self.string(fldtype, ddict["t"], "???? " + str(payload))
                print(line)
            return

        if self.__pdaq_only and svc != "pdaq":
            return

        varname = payload["varname"]

        if svc == "sndaq":
            if varname == "log" or self.__show_all:
                line = self.string(self.FIELD_SNDAQ, payload["time"],
                                   str(payload["value"]))
                print(line)
            return

        if svc == "pdaq" and varname == "log":
            line = self.__color_log(payload["time"], payload["value"])
            print(line)
            return

        if not self.__non_log:
            return

        line = self.string(self.FIELD_LIVE_MISC, ddict["t"],
                           svc + ":" + varname)
        print(line)
        line = self.string(self.FIELD_LIVE_MISC, "\t", str(payload))
        print(line)

    def read_file(self):
        prevline = None
        for line in self.__fd:
            if line is None:
                break

            stripped = line.strip()
            if stripped.startswith("livecontrol") or \
              stripped.startswith("livecmd"):
                if prevline is not None:
                    self.__process_control(prevline.rstrip())
                is_rate = line.find(" physics events") >= 0 and \
                          line.find(" moni events") >= 0 and \
                          line.find(" SN events") >= 0 and \
                          line.find(" tcals") >= 0
                is_reg = line.find(" Registered ") >= 0
                if not is_rate and not is_reg:
                    # cache non-rate lines in case there's an embedded newline
                    prevline = line
                else:
                    self.__process_control(line.rstrip())
                    prevline = None
            elif prevline is not None:
                # if line didn't start with 'livecontrol', the previous
                # line probably contained embedded newlines
                prevline += line
            else:
                print("Ignoring bad line: " + line, file=sys.stderr)

        if prevline is not None:
            self.__process_control(prevline.rstrip())

    @classmethod
    def string(cls, field, date, msg):
        if field not in cls.COLORS:
            colors = cls.COLORS[ColorFileParser.DEFAULT_FIELD]
        else:
            colors = cls.COLORS[field]

        if cls.TTYOUT:
            off = ANSIEscapeCode.OFF
        else:
            off = ""

        if date is None:
            dstr = ""
        else:
            dstr = "%s " % (date, )

        if not cls.TTYOUT or colors is None or len(colors) == 0:
            cstr = ""
        else:
            cstr = foreground_color(colors[0])
            if len(colors) >= 2:
                cstr += background_color(colors[1])
                if len(colors) > 2:
                    cstr += colors[2]
        return dstr + cstr + msg + off


if __name__ == "__main__":
    import argparse
    from DumpThreads import DumpThreadsOnSignal

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    DumpThreadsOnSignal(fd=sys.stderr)

    tail_logs(args)
