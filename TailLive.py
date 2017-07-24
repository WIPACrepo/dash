#!/usr/bin/env python
#
# Add color to `livecmd tail` output so it's more readable

import ast
import datetime
import os
import re
import subprocess
import sys
import threading
import Queue


def add_arguments(parser):
    parser.add_argument("-A", "--all-logs", dest="all_logs",
                        action="store_true", default=False,
                        help=("Read all log files instead of 'tail'ing"
                              " the most recent"))
    parser.add_argument("-a", "--all", dest="all_data",
                        action="store_true", default=False,
                        help="Show all data")
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
    parser.add_argument("files", nargs="*")


def tail_logs(args):
    if len(args.files) > 0:
        log = AllFiles(args.files)
    elif args.all_logs:
        log = AllLogs()
    else:
        log = Tail(args.tail_lines)

    LiveLog(log, args.all_data, args.pdaq_only, args.non_log,
            args.quiet).read_file()


class ANSIEscape(object):
    "ANSI escape codes"

    @classmethod
    def background_color(cls, color):
        "Return the string to set the background color"
        if color < 0 or color > 9:
            raise ValueError("Color %d is not between 0 and 9" % color)
        return cls.escape(color + 40)

    @classmethod
    def escape(cls, code):
        if code <= 0:
            substr = ""
        else:
            substr = str(code)
        return "\033[" + substr + "m"

    @classmethod
    def foreground_color(cls, color):
        if color < 0 or color > 9:
            raise ValueError("Color %d is not between 0 and 9" % color)
        return cls.escape(color + 30)


class Colorize(object):

    BLACK = 0
    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7
    DEFAULT = 9

    OFF = ANSIEscape.escape(0)

    BOLD_ON = ANSIEscape.escape(1)
    ITALIC_ON = ANSIEscape.escape(3)
    UNDERLINE_ON = ANSIEscape.escape(4)
    INVERTED_ON = ANSIEscape.escape(7)
    BOLD_OFF = ANSIEscape.escape(21)
    BOLD_FAINT_OFF = ANSIEscape.escape(22)
    ITALIC_OFF = ANSIEscape.escape(23)
    UNDERLINE_OFF = ANSIEscape.escape(24)
    INVERTED_OFF = ANSIEscape.escape(27)

    FG_BLACK = ANSIEscape.foreground_color(BLACK)
    FG_RED = ANSIEscape.foreground_color(RED)
    FG_GREEN = ANSIEscape.foreground_color(GREEN)
    FG_YELLOW = ANSIEscape.foreground_color(YELLOW)
    FG_BLUE = ANSIEscape.foreground_color(BLUE)
    FG_MAGENTA = ANSIEscape.foreground_color(MAGENTA)
    FG_CYAN = ANSIEscape.foreground_color(CYAN)
    FG_WHITE = ANSIEscape.foreground_color(WHITE)
    FG_DEFAULT = ANSIEscape.foreground_color(DEFAULT)

    BG_BLACK = ANSIEscape.background_color(BLACK)
    BG_RED = ANSIEscape.background_color(RED)
    BG_GREEN = ANSIEscape.background_color(GREEN)
    BG_YELLOW = ANSIEscape.background_color(YELLOW)
    BG_BLUE = ANSIEscape.background_color(BLUE)
    BG_MAGENTA = ANSIEscape.background_color(MAGENTA)
    BG_CYAN = ANSIEscape.background_color(CYAN)
    BG_WHITE = ANSIEscape.background_color(WHITE)
    BG_DEFAULT = ANSIEscape.background_color(DEFAULT)

    # if the output isn't a terminal, don't add ANSI escapes
    TTYOUT = sys.stdout.isatty()

    @classmethod
    def string(cls, date, msg, color=""):
        if cls.TTYOUT:
            off = cls.OFF
        else:
            color = ""
            off = ""

        return str(date) + " " + color + msg + off


class LiveLogException(Exception):
    pass


class LiveData(object):
    TYPE_LOG = 1
    TYPE_MONI = 2
    TYPE_LOGMONI = 3
    TYPE_ALERT = 4
    TYPE_MSGERR = 5
    TYPE_WARN = 6
    TYPE_UNKNOWN = 99

    def __init__(self, dtype):
        self.__datatype = dtype

    def datatype(self):
        return self.__datatype

    def is_text(self):
        raise NotImplementedError()

    @property
    def typestring(self):
        if self.__datatype == self.TYPE_LOG:
            return "LOG"
        if self.__datatype == self.TYPE_MONI:
            return "MONI"
        if self.__datatype == self.TYPE_LOGMONI:
            return "LOGMONI"
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

    def is_text(self):
        return True

    def data(self):
        return self.__text


class DictData(LiveData):
    def __init__(self, dtype, ddict):
        self.__dict = ddict

        super(DictData, self).__init__(dtype)

    def __str__(self):
        return "[%s] %s" % (self.typestring, self.__dict)

    def is_text(self):
        return False

    def data(self):
        return self.__dict


class LiveLine(object):
    PREFIX_PAT = re.compile(r"^\s+livecontrol\((\S+)\)" +
                            r"\s+(\d+-\d+-\d+ \d+:\d+:\d+,\d+)\s+(.*)$",
                            re.DOTALL)
    TIME_FMT = "%Y-%m-%d %H:%M:%S,%f"

    OLDLOG_PAT = re.compile(r"(\S+)\(([^\)\:]+)\:([^\)]+)\)\s+(\d+)" +
                            r" \[(\d+-\d+-\d+ \d+:\d+:\d+)(\.\d+)?\]\s+(.*)$")

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
                print >>sys.stderr, node
                for attrname in attrs:
                    print >>sys.stderr, '    %s ==> %s' % \
                        (attrname, getattr(node, attrname))
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
                payload = {
                    "service": match.group(1),
                    "varname": match.group(2),
                    "prio": prio,
                    "time": dtstr,
                    "value": match.group(7),
                }
                return DictData(DictData.TYPE_LOG, cls.__wrap_payload(payload))

        if line.startswith("WARN_MONI_SEND: "):
            try:
                ddict = cls.__parse_datetime_dict(line[16:], debug=debug)
                return DictData(DictData.TYPE_MONI, ddict)
            except:
                pass

        if line.startswith("{"):
            try:
                ddict = cls.__parse_datetime_dict(line, debug=debug)
                return DictData(DictData.TYPE_LOGMONI, ddict)
            except:
                pass

        if line.startswith("Got user-generated alert message: \"") and \
           line.endswith("\""):
            try:
                ddict = cls.__parse_datetime_dict(line[35:-1], debug=debug)
                return DictData(DictData.TYPE_ALERT, cls.__wrap_payload(ddict))
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

    def data(self):
        return self.__data

    def msgtype(self):
        return self.__msgtype

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
    def __init__(self, num_lines=None):
        self.__proc = None

        super(Tail, self).__init__()

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

    def next(self):
        return self.readline()

    def close(self):
        self.__proc.kill()

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

    def next_file(self):
        raise NotImplementedError()

    def next(self):
        return self.readline()

    def close(self):
        self.__fd.close()

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
            print >> sys.stderr, "File \"%s\" does not exist" % path


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


class LiveLog(Colorize):
    def __init__(self, fd, show_all=False, pdaq_only=False, non_log=False,
                 quiet=False):
        self.__fd = fd
        self.__show_all = show_all
        self.__pdaq_only = pdaq_only
        self.__non_log = non_log
        self.__quiet = quiet

        super(LiveLog, self).__init__()

    def __color_log(self, date, msg):
        if msg.find("ShutdownHook") > 0:
            return None

        if msg.find(" physics events") > 0 and \
                msg.find(" moni events") > 0:
            # rate line
            return self.string(date, msg, self.FG_GREEN + self.BG_WHITE)

        if msg.startswith("Registered "):
            # registered
            if self.__quiet:
                return None
            return self.string(date, msg)

        if msg.startswith("Waiting for ") or \
                (msg.startswith("RunSet #") and
                 msg.find("Waiting for ")):
            # waiting for
            return self.string(date, msg, self.FG_MAGENTA + self.BG_WHITE)

        if msg.startswith("Loading run configuration ") or \
                msg.startswith("Loaded run configuration "):
            # run config
            return self.string(date, msg)

        if msg.startswith("Starting run ") or \
                msg.startswith("Version info: ") or \
                msg.startswith("Run configuration: ") or \
                msg.startswith("Cluster: "):
            # run start
            return self.string(date, msg, self.FG_BLUE + self.BG_WHITE)

        if msg.find(" physics events collected in ") > 0 or \
                msg.find(" moni events, ") > 0 or \
                msg.startswith("Run terminated "):
            # run end
            return self.string(date, msg, self.FG_BLUE + self.BG_WHITE)

        if msg.startswith("Cycling components") or \
                msg.startswith("Built runset #"):
            # cycle components
            return self.string(date, msg)

        if msg.startswith("Run is healthy again"):
            # whew
            return self.string(date, msg, self.BG_GREEN + self.FG_BLACK)

        return self.string(date, msg, self.FG_RED + self.BG_YELLOW)

    def process(self, liveline):
        data = liveline.data()
        if data.is_text():
            color = self.FG_RED + self.BG_YELLOW
            if data.datatype() == LiveData.TYPE_UNKNOWN:
                color += self.BOLD_ON

            msg = data.data()
            if msg.find("flowed max message size in queue ITSQueue") > 0 or \
                    msg.startswith("Sent ITS Message: "):
                # ignore noisy Live errors
                pass
            elif msg.find("unable to send message") >= 0 and \
                    msg.find("in queue ITSQueue!!!") > 0:
                pass
            else:
                print self.string(liveline.timestamp(), msg, color)

            return

        ddict = data.data()
        svc = ddict["service"]

        if svc == "livecontrol":
            if self.__show_all:
                print self.string(ddict["t"], str(ddict["payload"]))
            return

        if self.__pdaq_only and svc != "pdaq":
            return

        if "payload" not in ddict or \
           "varname" not in ddict["payload"]:
            color = self.FG_RED + self.BG_YELLOW + self.BOLD_ON
            print self.string("BadDict ", str(ddict), color)
            return

        varname = ddict["payload"]["varname"]

        if varname == "log":
            line = self.__color_log(ddict["payload"]["time"],
                                    ddict["payload"]["value"])
            if line is not None:
                print line
            return

        if not self.__non_log:
            return

        color = self.FG_YELLOW + self.BG_BLACK
        print self.string(ddict["t"], svc + ":" + varname, color)
        print self.string("\t", str(ddict["payload"]), color)

    def read_file(self):
        prevline = None
        for line in self.__fd:
            if line is None:
                break

            if line.startswith("    livecontrol"):
                if prevline is not None:
                    self.process(LiveLine(prevline.rstrip()))
                if line.find(" physics events") < 0 or \
                   line.find(" moni events") < 0 or \
                   line.find(" SN events") < 0 or line.find(" tcals") < 0:
                    # cache non-rate lines in case there's an embedded newline
                    prevline = line
                else:
                    self.process(LiveLine(line.rstrip()))
                    prevline = None
            elif prevline is not None:
                # if line didn't start with 'livecontrol', the previous
                # line probably contained embedded newlines
                prevline += line
            else:
                print >> sys.stderr, "Ignoring bad line: " + line

        if prevline is not None:
            self.process(LiveLine(prevline.rstrip()))


if __name__ == "__main__": #pylint: disable=wrong-import-position
    import argparse

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    tail_logs(args)
