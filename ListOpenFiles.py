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
        rtnstr = ""
        if self.__user is not None:
            if self.__uid is not None:
                rtnstr = "%s(#%d)" % (self.__user, self.__uid)
            else:
                rtnstr = self.__user
        elif self.__uid is not None:
            rtnstr = "U#%d" % self.__uid
        else:
            rtnstr = "<UnknownUser>"

        if self.__pid is not None:
            rtnstr += " PID %d" % self.__pid

        if self.__ppid is not None:
            rtnstr += " PARENT %d" % self.__ppid

        if self.__pgid is not None:
            rtnstr += " PGRP %d" % self.__pgid

        if self.__command is not None:
            rtnstr += ": " + self.__command

        return rtnstr

    def add_file(self, fnm):
        if self.__file_list is None:
            self.__file_list = []
        self.__file_list.append(fnm)

    @property
    def command(self):
        if self.__command is None:
            return ""
        return self.__command.split()[0]

    @command.setter
    def command(self, val):
        self.__command = val

    @property
    def files(self):
        if self.__file_list is None:
            raise ListOpenFileException("No files available")
        for entry in self.__file_list:
            yield entry

    @property
    def pid(self):
        return self.__pid

    @pid.setter
    def pid(self, val):
        self.__pid = val

    def set_parent_process_id(self, val):
        self.__ppid = val

    def set_process_group_id(self, val):
        self.__pgid = val

    def set_security_context(self, val):
        self.__sec_context = val

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
        rtnstr = "%s#%s" % (type(self).__name__, self.__file_desc)

        if self.__access_mode is not None and self.__access_mode != "":
            rtnstr += "(%s)" % self.__access_mode

        if self.__name is not None:
            rtnstr += " " + self.__name

        if self.__lock_status is not None and self.__lock_status != "":
            rtnstr += " LCK %s" % self.__lock_status

        return rtnstr

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

    @property
    def flags(self):
        return self.__flags

    @flags.setter
    def flags(self, val):
        self.__flags = val

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

    @name.setter
    def name(self, val):
        self.__name = val

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

    @property
    def size_offset(self):
        if self.__size is None:
            return ""
        return str(self.__size)

    @size_offset.setter
    def size_offset(self, val):
        self.__size = val


class CharacterFile(StandardFile):
    @property
    def device(self):
        return self.flags

    @property
    def size_offset(self):
        return super(CharacterFile, self).offset


class NoFile(BaseFile):
    pass


class Directory(StandardFile):
    pass


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

    def add_info(self, val):
        if self.__info is None:
            self.__info = []
        self.__info.append(val)

    @property
    def inode(self):
        return self.__proto

    @property
    def name(self):
        name = super(BaseIP, self).name
        if self.__info is None:
            return name
        for info in self.__info:
            if info.startswith("ST="):
                name += " (%s)" % info[3:]
        return name

    @property
    def protocol(self):
        return self.__proto

    @protocol.setter
    def protocol(self, val):
        self.__proto = val


class IPv4(BaseIP):
    pass


class IPv6(BaseIP):
    pass


class KQueue(BaseFile):
    pass


class Pipe(BaseFile):
    def __init__(self, file_type, file_desc, access_mode, lock_status):
        super(Pipe, self).__init__(file_type, file_desc, access_mode,
                                   lock_status)
        self.__size = None

    @property
    def size_offset(self):
        return self.__size

    @size_offset.setter
    def size_offset(self, val):
        self.__size = val


class RegularFile(StandardFile):
    pass


class EventPoll(StandardFile):
    pass


class SystemFile(BaseFile):
    pass


class UnixSocket(BaseFile):
    pass


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
    @property
    def size_offset(self):
        pass

    @size_offset.setter
    def size_offset(self, val):
        pass


class ListOpenFiles(object):
    @classmethod
    def __create(cls, file_desc, access_mode, lock_status, file_type=None):
        if file_type is None:
            return NoFile(file_type, file_desc, access_mode, lock_status)
        if file_type == "CHR":
            return CharacterFile(file_type, file_desc, access_mode,
                                 lock_status)
        if file_type == "DIR":
            return Directory(file_type, file_desc, access_mode, lock_status)
        if file_type == "FIFO":
            return FIFO(file_type, file_desc, access_mode, lock_status)
        if file_type == "IPv4":
            return IPv4(file_type, file_desc, access_mode, lock_status)
        if file_type == "IPv6":
            return IPv6(file_type, file_desc, access_mode, lock_status)
        if file_type == "KQUEUE":
            return KQueue(file_type, file_desc, access_mode, lock_status)
        if file_type == "PIPE":
            return Pipe(file_type, file_desc, access_mode, lock_status)
        if file_type == "REG":
            return RegularFile(file_type, file_desc, access_mode, lock_status)
        if file_type == "sock":
            return UnknownSocket(file_type, file_desc, access_mode,
                                 lock_status)
        if file_type == "systm":
            return SystemFile(file_type, file_desc, access_mode, lock_status)
        if file_type == "unix":
            return UnixSocket(file_type, file_desc, access_mode, lock_status)
        if file_type == "unknown":
            return NoFile(file_type, file_desc, access_mode, lock_status)
        if file_type == "0000":
            return EventPoll(file_type, file_desc, access_mode, lock_status)

        return UnknownEntry(file_type, file_desc, access_mode, lock_status)

    @classmethod
    def __parse_output(cls, fin):
        tmp_info = []
        cur_file = None

        cur_user = None
        user_list = []

        for line in fin:
            line = line.rstrip()
            if line == "":
                continue

            if line.startswith("f"):
                # file descriptor
                if len(tmp_info) > 0:
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
                if len(tmp_info) != 1:
                    errmsg = "Parse error for access mode (%s)" % tmp_info
                    raise ListOpenFileException(errmsg)
                tmp_info.append(line[1:])
            elif line.startswith("l"):
                # file lock status
                if len(tmp_info) != 2:
                    errmsg = "Parse error for lock status (%s)" % tmp_info
                    raise ListOpenFileException(errmsg)
                tmp_info.append(line[1:])
                if tmp_info[0] == "NOFD":
                    if cur_user is None:
                        errmsg = "No user specified for current file %s" % \
                                 cur_file
                        raise ListOpenFileException(errmsg)

                    cur_file = cls.__create(tmp_info[0], tmp_info[1],
                                            tmp_info[2])
                    cur_user.add_file(cur_file)
                    tmp_info = []
            elif line.startswith("t"):
                # file type
                if len(tmp_info) != 3:
                    errmsg = "Parse error for file type (%s)" % tmp_info
                    raise ListOpenFileException(errmsg)

                if cur_user is None:
                    errmsg = "No user specified for current file %s" % cur_file
                    raise ListOpenFileException(errmsg)

                cur_file = cls.__create(tmp_info[0], tmp_info[1], tmp_info[2],
                                        line[1:])
                cur_user.add_file(cur_file)
                tmp_info = []
            elif line.startswith("D"):
                if cur_file is None:
                    errmsg = "Parse error for major/minor (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.major_minor_device = line[1:]
            elif line.startswith("G"):
                if cur_file is None:
                    errmsg = "Parse error for file flags (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.flags = line[1:]
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

                cur_user.set_parent_process_id(int(line[1:]))
            elif line.startswith("T"):
                if cur_file is None:
                    errmsg = "Parse error for TCP info (no cur_file)"
                    raise ListOpenFileException(errmsg)

                cur_file.add_info(line[1:])
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

                cur_user.set_process_group_id(int(line[1:]))
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

                cur_file.name = line[1:]
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

                cur_file.size_offset = int(line[1:])
            elif line.startswith("u"):
                if cur_user is None:
                    errmsg = "Parse error for user ID (no cur_user)"
                    raise ListOpenFileException(errmsg)

                cur_user.uid = int(line[1:])
            else:
                print("Unknown field \"%s\", value \"%s\"" %
                      (line[0], line[1:]))
                break

        return user_list

    @classmethod
    def dump(cls):
        cls.print_list(cls.run())

    @classmethod
    def print_list(cls, user_list):
        print("%-9.9s %4s %4s %4.4s%1.1s%1.1s %6.6s %10.10s %9.9s %8.8s %s" %
              ("COMMAND", "PID", "USER", "FD", "", "", "TYPE", "DEVICE",
               "SIZE/OFF", "NODE", "NAME"))
        for usr in user_list:
            cmd = usr.command
            pid = usr.pid
            user = usr.user
            if user is None:
                uid = usr.uid
                if uid is not None:
                    user = "#%d" % uid

            for fdata in usr.files:
                print("%-9.9s %4d %4s %4.4s%1.1s%1.1s %6.6s %10.10s %9.9s"
                      " %8.8s %s" %
                      (cmd, pid, user, fdata.file_desc, fdata.access_mode,
                       fdata.lock_status, fdata.file_type, fdata.device,
                       fdata.size_offset, fdata.inode, fdata.name))

    @classmethod
    def read_file(cls, filename):
        with open(filename, "r") as fin:
            return cls.__parse_output(fin)

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
            user_list = cls.__parse_output(proc.stdout)
        finally:
            proc.stdout.close()
        proc.wait()

        return user_list


def main():
    "Main program"

    if len(sys.argv) == 1:
        user_list = ListOpenFiles.run()
    else:
        user_list = ListOpenFiles.read_file(sys.argv[1])

    ListOpenFiles.print_list(user_list)


if __name__ == "__main__":
    main()
