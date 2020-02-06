#!/usr/bin/env python

from __future__ import print_function

import subprocess
import sys


class ListOpenFileException(Exception):
    pass


class UserInfo(object):
    def __init__(self):
        self.__file_list = None
        self.__pid = None
        self.__pgid = None
        self.__ppid = None
        self.__command = None
        self.__uid = None
        self.__sec_context = None
        self.__user = None

    def __str__(self):
        s = ""
        if self.__user is not None:
            if self.__uid is not None:
                s = "%s(#%d)" % (self.__user, self.__uid)
            else:
                s = self.__user
        elif self.__uid is not None:
            s = "U#%d" % self.__uid
        else:
            s = "<UnknownUser>"

        if self.__pid is not None:
            s += " PID %d" % self.__pid

        if self.__ppid is not None:
            s += " PARENT %d" % self.__ppid

        if self.__pgid is not None:
            s += " PGRP %d" % self.__pgid

        if self.__command is not None:
            s += ": " + self.__command

        return s

    def add_file(self, f):
        if self.__file_list is None:
            self.__file_list = []
        self.__file_list.append(f)

    @property
    def files(self):
        if self.__file_list is None:
            raise ListOpenFileException("No files available")
        for f in self.__file_list:
            yield f

    def setParentProcessID(self, val):
        self.__ppid = val

    def setProcessGroupID(self, val):
        self.__pgid = val

    def setSecurityContext(self, val):
        self.__sec_context = val

    @property
    def command(self):
        if self.__command is None:
            return ""
        return self.__command.split()[0]

    @command.setter
    def command(self, val):
        self.__command = val

    @property
    def pid(self):
        return self.__pid

    @pid.setter
    def pid(self, val):
        self.__pid = val

    @property
    def uid(self):
        return self.__uid

    @uid.setter
    def uid(self, val):
        self.__uid = val

    @property
    def user(self):
        return self.__user

    @user.setter
    def user(self, val):
        self.__user = val


class BaseFile(object):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        self.__file_type = file_type
        self.__file_desc = file_desc
        self.__access_mode = access_mode
        self.__lock_status = lock_status
        self.__name = None
        self.__inode = None
        self.__link_count = None
        self.__flags = None
        self.__offset = None
        self.__dev_char_code = None

    def __str__(self):
        s = "%s#%s" % (type(self).__name__, self.__file_desc)

        if self.__access_mode is not None and len(self.__access_mode) > 0:
            s += "(%s)" % self.__access_mode

        if self.__name is not None:
            s += " " + self.__name

        if self.__lock_status is not None and len(self.__lock_status) > 0:
            s += " LCK %s" % self.__lock_status

        return s

    @property
    def access_mode(self):
        return self.__access_mode

    @property
    def device(self):
        if self.__dev_char_code is None:
            return ""
        return self.__dev_char_code

    @device.setter
    def device(self, val):
        self.__dev_char_code = val

    @property
    def file_desc(self):
        return self.__file_desc

    @property
    def file_type(self):
        return self.__file_type

    def flags(self):
        return self.__flags

    @property
    def inode(self):
        if self.__inode is None:
            return ""
        return self.__inode

    @inode.setter
    def inode(self, val):
        self.__inode = val

    @property
    def link_count(self, val):
        self.__link_count = val

    @link_count.setter
    def link_count(self, val):
        self.__link_count = val

    @property
    def lock_status(self):
        return self.__lock_status

    @property
    def name(self):
        return self.__name

    @property
    def offset(self):
        return self.__offset

    @offset.setter
    def offset(self, val):
        self.__offset = val

    @property
    def protocol(self):
        return None

    @property
    def size_offset(self):
        if self.__offset is None:
            return ""
        return self.__offset

    def setFlags(self, val):
        self.__flags = val

    def setName(self, val):
        self.__name = val


class StandardFile(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(StandardFile, self).__init__(file_type, file_desc, access_mode,
                                           lock_status)
        self.__major_minor_dev = None
        self.__size = None

    @property
    def device(self):
        if self.__major_minor_dev is None:
            return ""
        return "%d,%d" % (self.__major_minor_dev >> 24,
                          self.__major_minor_dev & 0xffffff)

    @property
    def major_minor_device(self):
        return self.__major_minor_dev

    @major_minor_device.setter
    def major_minor_device(self, val):
        self.__major_minor_dev = int(val, 16)

    def setSize(self, val):
        self.__size = val

    @property
    def size_offset(self):
        if self.__size is None:
            return ""
        return str(self.__size)


class CharacterFile(StandardFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(CharacterFile, self).__init__(file_type, file_desc, access_mode,
                                            lock_status)

    @property
    def device(self):
        return self.flags()

    @property
    def size_offset(self):
        return super(CharacterFile, self).offset


class NoFile(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(NoFile, self).__init__(file_type, file_desc, access_mode,
                                     lock_status)


class Directory(StandardFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(Directory, self).__init__(file_type, file_desc, access_mode,
                                        lock_status)


class FIFO(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(FIFO, self).__init__(file_type, file_desc, access_mode,
                                   lock_status)
        self.__major_minor_dev = None

    @property
    def major_minor_device(self):
        return self.__major_minor_dev

    @major_minor_device.setter
    def major_minor_device(self, val):
        self.__major_minor_dev = val


class BaseIP(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(BaseIP, self).__init__(file_type, file_desc, access_mode,
                                     lock_status)
        self.__proto = None
        self.__info = None

    def addInfo(self, val):
        if self.__info is None:
            self.__info = []
        self.__info.append(val)

    @property
    def inode(self):
        return self.__proto

    @property
    def name(self):
        nm = super(BaseIP, self).name
        if self.__info is None:
            return nm
        for i in self.__info:
            if i.startswith("ST="):
                nm += " (%s)" % i[3:]
        return nm

    @property
    def protocol(self):
        return self.__proto

    @protocol.setter
    def protocol(self, val):
        self.__proto = val


class IPv4(BaseIP):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(IPv4, self).__init__(file_type, file_desc, access_mode,
                                   lock_status)


class IPv6(BaseIP):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(IPv6, self).__init__(file_type, file_desc, access_mode,
                                   lock_status)


class KQueue(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(KQueue, self).__init__(file_type, file_desc, access_mode,
                                     lock_status)


class Pipe(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(Pipe, self).__init__(file_type, file_desc, access_mode,
                                   lock_status)
        self.__size = None

    def setSize(self, val):
        self.__size = val

    @property
    def size_offset(self):
        return self.__size


class RegularFile(StandardFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(RegularFile, self).__init__(file_type, file_desc, access_mode,
                                          lock_status)


class EventPoll(StandardFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(EventPoll, self).__init__(file_type, file_desc, access_mode,
                                        lock_status)


class SystemFile(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(SystemFile, self).__init__(file_type, file_desc, access_mode,
                                         lock_status)


class UnixSocket(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(UnixSocket, self).__init__(file_type, file_desc, access_mode,
                                         lock_status)


class UnknownSocket(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(UnknownSocket, self).__init__(file_type, file_desc, access_mode,
                                            lock_status)
        self.__major_minor_dev = None

    @property
    def major_minor_device(self):
        return self.__major_minor_dev

    @major_minor_device.setter
    def major_minor_device(self, val):
        self.__major_minor_dev = val


class UnknownEntry(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(UnknownEntry, self).__init__(file_type, file_desc, access_mode,
                                           lock_status)

    def setSize(self, val):
        pass


class ListOpenFiles(object):
    @classmethod
    def __create(cls, file_desc, access_mode, lock_status, file_type=None):
        if file_type is None:
            return NoFile(file_type, file_desc, access_mode, lock_status)
        elif file_type == "CHR":
            return CharacterFile(file_type, file_desc, access_mode, lock_status)
        elif file_type == "DIR":
            return Directory(file_type, file_desc, access_mode, lock_status)
        elif file_type == "FIFO":
            return FIFO(file_type, file_desc, access_mode, lock_status)
        elif file_type == "IPv4":
            return IPv4(file_type, file_desc, access_mode, lock_status)
        elif file_type == "IPv6":
            return IPv6(file_type, file_desc, access_mode, lock_status)
        elif file_type == "KQUEUE":
            return KQueue(file_type, file_desc, access_mode, lock_status)
        elif file_type == "PIPE":
            return Pipe(file_type, file_desc, access_mode, lock_status)
        elif file_type == "REG":
            return RegularFile(file_type, file_desc, access_mode, lock_status)
        elif file_type == "sock":
            return UnknownSocket(file_type, file_desc, access_mode, lock_status)
        elif file_type == "systm":
            return SystemFile(file_type, file_desc, access_mode, lock_status)
        elif file_type == "unix":
            return UnixSocket(file_type, file_desc, access_mode, lock_status)
        elif file_type == "unknown":
            return NoFile(file_type, file_desc, access_mode, lock_status)
        elif file_type == "0000":
            return EventPoll(file_type, file_desc, access_mode, lock_status)

        return UnknownEntry(file_type, file_desc, access_mode, lock_status)

    @classmethod
    def __parseOutput(cls, fd):
        tmp_info = None
        cur_file = None

        cur_user = None
        user_list = []

        for line in fd:
            line = line.rstrip()
            if len(line) == 0:
                continue

            if line.startswith("f"):
                # file descriptor
                if tmp_info is not None:
                    errmsg = "Parse error for file descriptor (%s)" % tmp_info
                    raise ListOpenFileException(errmsg)

                if cur_file is not None:
                    cur_file = None

                try:
                    val = int(line[1:])
                except ValueError:
                    val = line[1:]
                tmp_info = [val, ]
            elif line.startswith("a"):
                # file access mode
                if tmp_info is None or len(tmp_info) != 1:
                    errmsg = "Parse error for access mode (%s)" % tmp_info
                    raise ListOpenFileException(errmsg)
                tmp_info.append(line[1:])
            elif line.startswith("l"):
                # file lock status
                if tmp_info is None or len(tmp_info) != 2:
                    errmsg = "Parse error for lock status (%s)" % tmp_info
                    raise ListOpenFileException(errmsg)
                tmp_info.append(line[1:])
                if tmp_info[0] == "NOFD":
                    if cur_user is None:
                        errmsg = "No user specified for current file %s" % \
                                 cur_file
                        raise ListOpenFileException(errmsg)

                    cur_file = cls.__create(tmp_info[0], tmp_info[1], tmp_info[2])
                    cur_user.add_file(cur_file)
                    tmp_info = None
            elif line.startswith("t"):
                # file type
                if tmp_info is None or len(tmp_info) != 3:
                    errmsg = "Parse error for file type (%s)" % tmp_info
                    raise ListOpenFileException(errmsg)

                if cur_user is None:
                    errmsg = "No user specified for current file %s" % cur_file
                    raise ListOpenFileException(errmsg)

                cur_file = cls.__create(tmp_info[0], tmp_info[1], tmp_info[2],
                                       line[1:])
                cur_user.add_file(cur_file)
                tmp_info = None
            elif line.startswith("D"):
                if cur_file is None:
                    errmsg = "Parse error for major/minor (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.major_minor_device = line[1:]
            elif line.startswith("G"):
                if cur_file is None:
                    errmsg = "Parse error for file flags (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.setFlags(line[1:])
            elif line.startswith("L"):
                if cur_user is None:
                    errmsg = "Parse error for user name (no cur_user)"
                    raise ListOpenFileException(errmsg)

                cur_user.user = line[1:]
            elif line.startswith("P"):
                if cur_file is None:
                    errmsg = "Parse error for protocol (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.protocol = line[1:]
            elif line.startswith("R"):
                if cur_user is None:
                    errmsg = "Parse error for parent process ID (no cur_user)"
                    raise ListOpenFileException(errmsg)

                cur_user.setParentProcessID(int(line[1:]))
            elif line.startswith("T"):
                if cur_file is None:
                    errmsg = "Parse error for TCP info (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.addInfo(line[1:])
            elif line.startswith("Z"):
                if cur_user is None:
                    errmsg = "Parse error for parent process ID (no cur_user)"
                    raise ListOpenFileException(errmsg)

                cur_user.setSecurityContext(line[1:])
            elif line.startswith("c"):
                if cur_user is None:
                    errmsg = "Parse error for command name (no cur_user)"
                    raise ListOpenFileException(errmsg)

                cur_user.command = line[1:]
            elif line.startswith("d"):
                if cur_file is None:
                    errmsg = "Parse error for device character code" + \
                             " (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.device = line[1:]
            elif line.startswith("g"):
                if cur_user is None:
                    errmsg = "Parse error for process group ID (no cur_user)"
                    raise ListOpenFileException(errmsg)

                cur_user.setProcessGroupID(int(line[1:]))
            elif line.startswith("i"):
                if cur_file is None:
                    errmsg = "Parse error for inode (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.inode = int(line[1:])
            elif line.startswith("k"):
                if cur_file is None:
                    errmsg = "Parse error for link count (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.link_count = int(line[1:])
            elif line.startswith("n"):
                if cur_file is None:
                    errmsg = "Parse error for file name (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.setName(line[1:])
            elif line.startswith("o"):
                if cur_file is None:
                    errmsg = "Parse error for file offset (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.offset = line[1:]
            elif line.startswith("p"):
                cur_user = UserInfo()
                user_list.append(cur_user)

                cur_user.pid = int(line[1:])
            elif line.startswith("s"):
                if cur_file is None:
                    errmsg = "Parse error for file size (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.setSize(int(line[1:]))
            elif line.startswith("u"):
                if cur_user is None:
                    errmsg = "Parse error for user ID (no cur_user)"
                    raise ListOpenFileException(errmsg)

                cur_user.uid = int(line[1:])
            else:
                print("Unknown field \"%s\", value \"%s\"" % \
                      (line[0], line[1:]))
                break

        return user_list

    @classmethod
    def dump(cls):
        cls.dumpList(cls.run())

    @classmethod
    def dumpList(cls, user_list):
        print("%-9.9s %4s %4s %4.4s%1.1s%1.1s %6.6s %10.10s %9.9s %8.8s %s" % \
              ("COMMAND", "PID", "USER", "FD", "", "", "TYPE", "DEVICE",
               "SIZE/OFF", "NODE", "NAME"))
        for u in user_list:
            cmd = u.command
            pid = u.pid
            user = u.user
            if user is None:
                uid = u.uid
                if uid is not None:
                    user = "#%d" % uid

            for f in u.files:
                print("%-9.9s %4d %4s %4.4s%1.1s%1.1s %6.6s %10.10s %9.9s" \
                    " %8.8s %s" % \
                    (cmd, pid, user, f.file_desc, f.access_mode,
                     f.lock_status, f.file_type, f.device, f.size_offset,
                     f.inode, f.name))

    @classmethod
    def readOutput(cls, filename):
        with open(filename, "r") as fd:
            return cls.__parseOutput(fd)

    @classmethod
    def run(cls, pid=None):
        cmd = "lsof -F -a -d \"^cwd,^rtd,^txt,^mem\""
        if pid is not None:
            cmd += " -a -p %d" % pid
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        try:
            user_list = cls.__parseOutput(proc.stdout)
        finally:
            proc.stdout.close()
        proc.wait()

        return user_list


if __name__ == "__main__":
    if len(sys.argv) == 1:
        user_list = ListOpenFiles.run()
    else:
        user_list = ListOpenFiles.readOutput(sys.argv[1])

    ListOpenFiles.dumpList(user_list)
