#!/usr/bin/env python

import subprocess
import sys


class ListOpenFileException(Exception):
    pass


class UserInfo(object):
    def __init__(self):
        self.__fileList = None
        self.__pid = None
        self.__pgid = None
        self.__ppid = None
        self.__command = None
        self.__uid = None
        self.__secContext = None
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

    def addFile(self, f):
        if self.__fileList is None:
            self.__fileList = []
        self.__fileList.append(f)

    def files(self):
        if self.__fileList is None:
            raise ListOpenFileException("No files available")
        for f in self.__fileList:
            yield f

    def setCommand(self, val):
        self.__command = val

    def setParentProcessID(self, val):
        self.__ppid = val

    def setProcessGroupID(self, val):
        self.__pgid = val

    def setProcessID(self, val):
        self.__pid = val

    def setSecurityContext(self, val):
        self.__secContext = val

    def setUserID(self, val):
        self.__uid = val

    def setUserName(self, val):
        self.__user = val

    def command(self):
        if self.__command is None:
            return ""
        return self.__command.split()[0]

    def pid(self):
        return self.__pid

    def uid(self):
        return self.__uid

    def user(self):
        return self.__user


class BaseFile(object):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        self.__fileType = fileType
        self.__fileDesc = fileDesc
        self.__accessMode = accessMode
        self.__lockStatus = lockStatus
        self.__name = None
        self.__inode = None
        self.__linkCnt = None
        self.__flags = None
        self.__offset = None
        self.__devCharCode = None

    def __str__(self):
        s = "%s#%s" % (type(self).__name__, self.__fileDesc)

        if self.__accessMode is not None and len(self.__accessMode) > 0:
            s += "(%s)" % self.__accessMode

        if self.__name is not None:
            s += " " + self.__name

        if self.__lockStatus is not None and len(self.__lockStatus) > 0:
            s += " LCK %s" % self.__lockStatus

        return s

    def accessMode(self):
        return self.__accessMode

    def devCharCode(self):
        return self.__devCharCode

    def device(self):
        if self.__devCharCode is None:
            return ""
        return self.__devCharCode

    def fileDesc(self):
        return self.__fileDesc

    def fileType(self):
        return self.__fileType

    def flags(self):
        return self.__flags

    def inode(self):
        if self.__inode is None:
            return ""
        return self.__inode

    def lockStatus(self):
        return self.__lockStatus

    def name(self):
        return self.__name

    def offset(self):
        return self.__offset

    def protocol(self):
        return None

    def sizeOffset(self):
        if self.__offset is None:
            return ""
        return self.__offset

    def setDeviceCharacterCode(self, val):
        self.__devCharCode = val

    def setFlags(self, val):
        self.__flags = val

    def setInode(self, val):
        self.__inode = val

    def setLinkCount(self, val):
        self.__linkCnt = val

    def setName(self, val):
        self.__name = val

    def setOffset(self, val):
        self.__offset = val


class StandardFile(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(StandardFile, self).__init__(fileType, fileDesc, accessMode,
                                           lockStatus)
        self.__majorMinorDev = None
        self.__size = None

    def device(self):
        if self.__majorMinorDev is None:
            return ""
        return "%d,%d" % (self.__majorMinorDev >> 24,
                          self.__majorMinorDev & 0xffffff)

    def majorMinorDevice(self):
        return self.__majorMinorDev

    def setMajorMinorDevice(self, val):
        self.__majorMinorDev = int(val, 16)

    def setSize(self, val):
        self.__size = val

    def sizeOffset(self):
        if self.__size is None:
            return ""
        return str(self.__size)


class CharacterFile(StandardFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(CharacterFile, self).__init__(fileType, fileDesc, accessMode,
                                            lockStatus)

    def device(self):
        return self.flags()

    def sizeOffset(self):
        return super(CharacterFile, self).offset()


class NoFile(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(NoFile, self).__init__(fileType, fileDesc, accessMode,
                                     lockStatus)


class Directory(StandardFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(Directory, self).__init__(fileType, fileDesc, accessMode,
                                        lockStatus)


class FIFO(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(FIFO, self).__init__(fileType, fileDesc, accessMode, lockStatus)
        self.__majorMinorDev = None

    def setMajorMinorDevice(self, val):
        self.__majorMinorDev = val


class BaseIP(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(BaseIP, self).__init__(fileType, fileDesc, accessMode,
                                     lockStatus)
        self.__proto = None
        self.__info = None

    def addInfo(self, val):
        if self.__info is None:
            self.__info = []
        self.__info.append(val)

    def inode(self):
        return self.__proto

    def name(self):
        nm = super(BaseIP, self).name()
        if self.__info is None:
            return nm
        for i in self.__info:
            if i.startswith("ST="):
                nm += " (%s)" % i[3:]
        return nm

    def protocol(self):
        return self.__proto

    def setProtocol(self, val):
        self.__proto = val


class IPv4(BaseIP):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(IPv4, self).__init__(fileType, fileDesc, accessMode, lockStatus)


class IPv6(BaseIP):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(IPv6, self).__init__(fileType, fileDesc, accessMode, lockStatus)


class KQueue(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(KQueue, self).__init__(fileType, fileDesc, accessMode,
                                     lockStatus)


class Pipe(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(Pipe, self).__init__(fileType, fileDesc, accessMode, lockStatus)
        self.__size = None

    def setSize(self, val):
        self.__size = val

    def sizeOffset(self):
        return self.__size


class RegularFile(StandardFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(RegularFile, self).__init__(fileType, fileDesc, accessMode,
                                          lockStatus)


class SystemFile(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(SystemFile, self).__init__(fileType, fileDesc, accessMode,
                                         lockStatus)


class UnixSocket(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(UnixSocket, self).__init__(fileType, fileDesc, accessMode,
                                         lockStatus)


class UnknownSocket(BaseFile):
    def __init__(self, fileType, fileDesc, accessMode, lockStatus):
        super(UnknownSocket, self).__init__(fileType, fileDesc, accessMode,
                                            lockStatus)
        self.__majorMinorDev = None

    def setMajorMinorDevice(self, val):
        self.__majorMinorDev = val


class ListOpenFiles(object):
    @classmethod
    def __create(cls, fileDesc, accessMode, lockStatus, fileType=None):
        if fileType is None:
            return NoFile(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "CHR":
            return CharacterFile(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "DIR":
            return Directory(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "FIFO":
            return FIFO(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "IPv4":
            return IPv4(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "IPv6":
            return IPv6(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "KQUEUE":
            return KQueue(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "PIPE":
            return Pipe(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "REG":
            return RegularFile(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "sock":
            return UnknownSocket(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "systm":
            return SystemFile(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "unix":
            return UnixSocket(fileType, fileDesc, accessMode, lockStatus)
        elif fileType == "unknown":
            return NoFile(fileType, fileDesc, accessMode, lockStatus)

        raise ListOpenFileException("Found unknown file type \"%s\"" %
                                    fileType)

    @classmethod
    def __parseOutput(cls, fd):
        debug = True

        tmpInfo = None
        curFile = None

        curUser = None
        userList = []

        for line in fd:
            line = line.rstrip()
            if len(line) == 0:
                continue

            if line.startswith("f"):
                # file descriptor
                if tmpInfo is not None:
                    errmsg = "Parse error for file descriptor (%s)" % tmpInfo
                    raise ListOpenFileException(errmsg)

                if curFile is not None:
                    curFile = None

                try:
                    val = int(line[1:])
                except ValueError:
                    val = line[1:]
                tmpInfo = [val, ]
            elif line.startswith("a"):
                # file access mode
                if tmpInfo is None or len(tmpInfo) != 1:
                    errmsg = "Parse error for access mode (%s)" % tmpInfo
                    raise ListOpenFileException(errmsg)
                tmpInfo.append(line[1:])
            elif line.startswith("l"):
                # file lock status
                if tmpInfo is None or len(tmpInfo) != 2:
                    errmsg = "Parse error for lock status (%s)" % tmpInfo
                    raise ListOpenFileException(errmsg)
                tmpInfo.append(line[1:])
                if tmpInfo[0] == "NOFD":
                    if curUser is None:
                        errmsg = "No user specified for current file %s" % \
                                 curFile
                        raise ListOpenFileException(errmsg)

                    curFile = cls.__create(tmpInfo[0], tmpInfo[1], tmpInfo[2])
                    curUser.addFile(curFile)
                    tmpInfo = None
            elif line.startswith("t"):
                # file type
                if tmpInfo is None or len(tmpInfo) != 3:
                    errmsg = "Parse error for file type (%s)" % tmpInfo
                    raise ListOpenFileException(errmsg)

                if curUser is None:
                    errmsg = "No user specified for current file %s" % curFile
                    raise ListOpenFileException(errmsg)

                curFile = cls.__create(tmpInfo[0], tmpInfo[1], tmpInfo[2],
                                       line[1:])
                curUser.addFile(curFile)
                tmpInfo = None
            elif line.startswith("D"):
                if curFile is None:
                    errmsg = "Parse error for major/minor (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setMajorMinorDevice(line[1:])
            elif line.startswith("G"):
                if curFile is None:
                    errmsg = "Parse error for file flags (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setFlags(line[1:])
            elif line.startswith("L"):
                if curUser is None:
                    errmsg = "Parse error for user name (no curUser)"
                    raise ListOpenFileException(errmsg)

                curUser.setUserName(line[1:])
            elif line.startswith("P"):
                if curFile is None:
                    errmsg = "Parse error for protocol (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setProtocol(line[1:])
            elif line.startswith("R"):
                if curUser is None:
                    errmsg = "Parse error for parent process ID (no curUser)"
                    raise ListOpenFileException(errmsg)

                curUser.setParentProcessID(int(line[1:]))
            elif line.startswith("T"):
                if curFile is None:
                    errmsg = "Parse error for TCP info (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.addInfo(line[1:])
            elif line.startswith("Z"):
                if curUser is None:
                    errmsg = "Parse error for parent process ID (no curUser)"
                    raise ListOpenFileException(errmsg)

                curUser.setSecurityContext(line[1:])
            elif line.startswith("c"):
                if curUser is None:
                    errmsg = "Parse error for command name (no curUser)"
                    raise ListOpenFileException(errmsg)

                curUser.setCommand(line[1:])
            elif line.startswith("d"):
                if curFile is None:
                    errmsg = "Parse error for device character code" + \
                             " (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setDeviceCharacterCode(line[1:])
            elif line.startswith("g"):
                if curUser is None:
                    errmsg = "Parse error for process group ID (no curUser)"
                    raise ListOpenFileException(errmsg)

                curUser.setProcessGroupID(int(line[1:]))
            elif line.startswith("i"):
                if curFile is None:
                    errmsg = "Parse error for inode (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setInode(long(line[1:]))
            elif line.startswith("k"):
                if curFile is None:
                    errmsg = "Parse error for link count (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setLinkCount(int(line[1:]))
            elif line.startswith("n"):
                if curFile is None:
                    errmsg = "Parse error for file name (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setName(line[1:])
            elif line.startswith("o"):
                if curFile is None:
                    errmsg = "Parse error for file offset (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setOffset(line[1:])
            elif line.startswith("p"):
                curUser = UserInfo()
                userList.append(curUser)

                curUser.setProcessID(int(line[1:]))
            elif line.startswith("s"):
                if curFile is None:
                    errmsg = "Parse error for file size (no curFile)"
                    raise ListOpenFileException(errmsg)

                curFile.setSize(long(line[1:]))
            elif line.startswith("u"):
                if curUser is None:
                    errmsg = "Parse error for user ID (no curUser)"
                    raise ListOpenFileException(errmsg)

                curUser.setUserID(int(line[1:]))
            else:
                print "Unknown field \"%s\", value \"%s\"" % \
                      (line[0], line[1:])
                break

        return userList

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
            userList = cls.__parseOutput(proc.stdout)
        finally:
            proc.stdout.close()
        proc.wait()

        return userList

if __name__ == "__main__":
    if len(sys.argv) == 1:
        userList = ListOpenFiles.run()
    else:
        userList = ListOpenFiles.readOutput(sys.argv[1])

    print "%-9.9s %4s %4s %4.4s%1.1s%1.1s %6.6s %10.10s %9.9s %8.8s %s" % \
          ("COMMAND", "PID", "USER", "FD", "", "", "TYPE", "DEVICE",
           "SIZE/OFF", "NODE", "NAME")
    for u in userList:
        cmd = u.command()
        pid = u.pid()
        user = u.user()
        if user is None:
            uid = u.uid()
            if uid is not None:
                user = "#%d" % uid

        for f in u.files():
            print ("%-9.9s %4d %4s %4.4s%1.1s%1.1s %6.6s %10.10s %9.9s" +
                   " %8.8s %s") % \
                   (cmd, pid, user, f.fileDesc(), f.accessMode(),
                    f.lockStatus(), f.fileType(), f.device(), f.sizeOffset(),
                    f.inode(), f.name())
