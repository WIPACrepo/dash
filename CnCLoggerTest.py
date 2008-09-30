#!/usr/bin/env python

import os, select, socket, time, unittest, threading
from CnCServer import CnCLogger

class SocketReader(object):
    def __init__(self, port):
        "Logpath should be fully qualified in case I'm a Daemon"
        self._port   = port

        self._logLines = []

        if os.name == "nt":
            self._thread = threading.Thread(target=self.win_listener)
        else:
            self._thread = threading.Thread(target=self.listener)

        self._go      = True
        self._serving = False
        self._thread.start()

    def win_listener(self):
        """
        Windows version of listener - no select().
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #self.sock.setblocking(1)
        #self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", self._port))
        self._serving = True
        while self._go:
            data = self.sock.recv(8192)
            self._logLines.append(data)
        self.sock.close()
        self._serving = False

    def listener(self):
        """
        Create listening, non-blocking UDP socket, read from it, and write to file;
        close socket and end thread if signaled via self._go variable.
        """
                 
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(0)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", self._port))
        self._serving = True
        pr = [self.sock]
        pw = []
        pe = [self.sock]
        while self._go:
            rd, rw, re = select.select(pr, pw, pe, 0.5)
            if len(re) != 0:
                raise Exception("Error on select was detected.")
            if len(rd) == 0:
                continue
            while 1: # Slurp up waiting packets, return to select if EAGAIN
                try:
                    data = self.sock.recv(8192, socket.MSG_DONTWAIT)
                    self._logLines.append(data)
                except Exception:
                    break # Go back to select so we don't busy-wait
        self.sock.close()
        self._serving = False

    def clear(self):
        self._logLines = []

    def numLines(self):
        return len(self._logLines)

    def logLine(self, idx):
        return self._logLines[idx]

    def serving(self):
        return self._serving

    def stopServing(self):
        "Signal listening thread to exit; wait for thread to finish"
        self._go = False
        if self._thread != None:
            self._thread.join()
            self._thread = None

    def waitForMessage(self, reps=1000):
        for i in range(reps):
            if len(self._logLines) > 0:
                break
            time.sleep(.001)

class CnCLoggerTest(unittest.TestCase):
    def testOpenReset(self):
        dc = CnCLogger(True)

        logHost = 'localhost'
        logPort = 12345

        logObj = SocketReader(logPort)
        while not logObj.serving():
            time.sleep(.001)

        try:
            self.failIf(dc.socketlog is not None, 'socketlog is not None')

            dc.openLog(logHost, logPort)
            self.failIf(dc.socketlog is None, 'socketlog is None')
            self.assertEqual(dc.logIP, logHost)
            self.assertEqual(dc.logPort, logPort)
            self.failIf(dc.prevIP is not None, 'prevIP is not empty')
            self.failIf(dc.prevPort is not None, 'prevPort is not empty')

            logObj.waitForMessage()

            self.assertEqual(logObj.numLines(), 1)
            if not logObj.logLine(0).endswith('Start of log at %s:%d' %
                                              (logHost, logPort)):
                self.fail('Bad log line %s' % logObj.logLine(0))
            logObj.clear()

            dc.resetLog()
            self.failIf(dc.socketlog is not None, 'socketlog is not None')
            self.failIf(dc.logIP is not None, 'logIP was not cleared')
            self.failIf(dc.logPort is not None, 'logPort was not cleared')
            self.failIf(dc.prevIP is not None, 'prevIP was not cleared')
            self.failIf(dc.prevPort is not None, 'prevPort was not cleared')

            self.assertEqual(logObj.numLines(), 0)
        finally:
            logObj.stopServing()

    def testOpenClose(self):
        dc = CnCLogger(True)

        logHost = 'localhost'
        logPort = 12345

        logObj = SocketReader(logPort)
        while not logObj.serving():
            time.sleep(.001)

        try:
            self.failIf(dc.socketlog is not None, 'socketlog is not None')

            dc.openLog(logHost, logPort)
            self.failIf(dc.socketlog is None, 'socketlog is None')
            self.assertEqual(dc.logIP, logHost)
            self.assertEqual(dc.logPort, logPort)
            self.failIf(dc.prevIP is not None, 'prevIP is not empty')
            self.failIf(dc.prevPort is not None, 'prevPort is not empty')

            logObj.waitForMessage()

            self.assertEqual(logObj.numLines(), 1)
            if not logObj.logLine(0).endswith('Start of log at %s:%d' %
                                              (logHost, logPort)):
                self.fail('Bad log line %s' % logObj.logLine(0))
            logObj.clear()

            dc.closeLog()
            self.failIf(dc.socketlog is not None, 'socketlog is not None')
            self.failIf(dc.logIP is not None, 'logIP was not cleared')
            self.failIf(dc.logPort is not None, 'logPort was not cleared')
            self.failIf(dc.prevIP is not None, 'prevIP was not cleared')
            self.failIf(dc.prevPort is not None, 'prevPort was not cleared')

            logObj.waitForMessage()

            self.assertEqual(logObj.numLines(), 1)
            if not logObj.logLine(0).endswith('End of log'):
                self.fail('Bad log line %s' % logObj.logLine(0))
            logObj.clear()
        finally:
            logObj.stopServing()

    def testLogFallback(self):
        dc = CnCLogger(True)

        dfltHost = 'localhost'
        dfltPort = 11111

        dfltObj = SocketReader(dfltPort)
        while not dfltObj.serving():
            time.sleep(.001)

        logHost = 'localhost'
        logPort = 12345

        logObj = SocketReader(logPort)
        while not logObj.serving():
            time.sleep(.001)

        try:
            self.failIf(dc.socketlog is not None, 'socketlog is not None')

            dc.openLog(dfltHost, dfltPort)
            self.failIf(dc.socketlog is None, 'socketlog is None')
            self.assertEqual(dc.logIP, dfltHost)
            self.assertEqual(dc.logPort, dfltPort)
            self.failIf(dc.prevIP is not None, 'prevIP is not empty')
            self.failIf(dc.prevPort is not None, 'prevPort is not empty')

            dfltObj.waitForMessage()

            self.assertEqual(dfltObj.numLines(), 1)
            if not dfltObj.logLine(0).endswith('Start of log at %s:%d' %
                                              (dfltHost, dfltPort)):
                self.fail('Bad log line %s' % dfltObj.logLine(0))
            dfltObj.clear()

            dc.openLog(logHost, logPort)
            self.failIf(dc.socketlog is None, 'socketlog is None')
            self.assertEqual(dc.logIP, logHost)
            self.assertEqual(dc.logPort, logPort)
            self.assertEqual(dc.prevIP, dfltHost)
            self.assertEqual(dc.prevPort, dfltPort)

            logObj.waitForMessage()

            self.assertEqual(dfltObj.numLines(), 0)

            self.assertEqual(logObj.numLines(), 1)
            if not logObj.logLine(0).endswith('Start of log at %s:%d' %
                                              (logHost, logPort)):
                self.fail('Bad log line %s' % logObj.logLine(0))
            logObj.clear()

            dc.closeLog()
            self.failIf(dc.socketlog is None, 'socketlog is None')
            self.assertEqual(dc.logIP, dfltHost)
            self.assertEqual(dc.logPort, dfltPort)
            self.failIf(dc.prevIP is not None, 'prevIP was not cleared')
            self.failIf(dc.prevPort is not None, 'prevPort was not cleared')

            logObj.waitForMessage()
            dfltObj.waitForMessage()

            self.assertEqual(dfltObj.numLines(), 1)
            if not dfltObj.logLine(0).endswith('Start of log at %s:%d' %
                                               (dfltHost, dfltPort)):
                self.fail('Bad log line %s' % dfltObj.logLine(0))
            dfltObj.clear()

            self.assertEqual(logObj.numLines(), 1)
            if not logObj.logLine(0).endswith('End of log'):
                self.fail('Bad log line %s' % logObj.logLine(0))
            logObj.clear()

            newHost = 'localhost'
            newPort = 45678

            newObj = SocketReader(newPort)
            while not newObj.serving():
                time.sleep(.001)

            try:
                dc.openLog(newHost, newPort)
                self.failIf(dc.socketlog is None, 'socketlog is None')
                self.assertEqual(dc.logIP, newHost)
                self.assertEqual(dc.logPort, newPort)
                self.assertEqual(dc.prevIP, dfltHost)
                self.assertEqual(dc.prevPort, dfltPort)

                newObj.waitForMessage()

                self.assertEqual(dfltObj.numLines(), 0)

                self.assertEqual(newObj.numLines(), 1)
                if not newObj.logLine(0).endswith('Start of log at %s:%d' %
                                                  (newHost, newPort)):
                    self.fail('Bad log line %s' % newObj.logLine(0))
                newObj.clear()

                dc.closeLog()
                self.failIf(dc.socketlog is None, 'socketlog is None')
                self.assertEqual(dc.logIP, dfltHost)
                self.assertEqual(dc.logPort, dfltPort)
                self.failIf(dc.prevIP is not None, 'prevIP was not cleared')
                self.failIf(dc.prevPort is not None, 'prevIP was not cleared')

                newObj.waitForMessage()
                dfltObj.waitForMessage()

                self.assertEqual(dfltObj.numLines(), 1)
                if not dfltObj.logLine(0).endswith('Start of log at %s:%d' %
                                                   (dfltHost, dfltPort)):
                    self.fail('Bad log line %s' % dfltObj.logLine(0))
                dfltObj.clear()

                self.assertEqual(newObj.numLines(), 1)
                if not newObj.logLine(0).endswith('End of log'):
                    self.fail('Bad log line %s' % newObj.logLine(0))
                newObj.clear()
            finally:
                newObj.stopServing()

            dc.closeLog()
            self.failIf(dc.socketlog is not None, 'socketlog is not None')
            self.assertEqual(dc.logIP, None)
            self.assertEqual(dc.logPort, None)

            dfltObj.waitForMessage()

            self.assertEqual(dfltObj.numLines(), 1)
            if not dfltObj.logLine(0).endswith('End of log'):
                self.fail('Bad log line %s' % dfltObj.logLine(0))
            dfltObj.clear()
        finally:
            try:
                dfltObj.stopServing()
            except:
                pass
            try:
                logObj.stopServing()
            except:
                pass

if __name__ == '__main__':
    unittest.main()
