#!/usr/bin/env python

import datetime, os, tempfile, time, unittest
from DAQLog import LogSocketServer

from DAQMocks import SocketWriter

class TestDAQLog(unittest.TestCase):
    DIR_PATH = None

    def checkLog(self, logPath, msgList):
        lines = self.readLog(logPath)
        self.assertEquals(len(msgList), len(lines), 'Expected %d line, not %d' %
                          (len(msgList), len(lines)))

        for i in range(len(msgList)):
            msg = lines[i].rstrip()
            self.assertEquals(msgList[i], msg,
                              'Expected "%s", not "%s"' % (msgList[i], msg))

    def readLog(self, logPath):
        lines = []
        fd = open(logPath, 'r')
        for line in fd:
            lines.append(line.rstrip())
        fd.close()
        return lines

    def setUp(self):
        self.sockLog = None

        TestDAQLog.DIR_PATH = tempfile.mkdtemp()

    def tearDown(self):
        if self.sockLog is not None:
            self.sockLog.stopServing()

        time.sleep(0.1)

        for root, dirs, files in os.walk(TestDAQLog.DIR_PATH, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(TestDAQLog.DIR_PATH)
        TestDAQLog.DIR_PATH = None

    def testLogSocketServer(self):
        port = 5432
        cname = 'foo'
        logPath = os.path.join(TestDAQLog.DIR_PATH, cname + '.log')

        self.sockLog = LogSocketServer(port, cname, logPath, True)
        self.sockLog.startServing()
        for i in range(5):
            if self.sockLog.isServing():
                break
            time.sleep(0.1)
        self.failUnless(os.path.exists(logPath), 'Log file was not created')
        self.failUnless(self.sockLog.isServing(), 'Log server was not started')

        now = datetime.datetime.now()
        msg = 'Test 1 2 3'

        client = SocketWriter('localhost', port)
        client.write_ts(msg, now)

        client.close()

        self.sockLog.stopServing()

        self.checkLog(logPath, ('%s - - [%s] %s' % (cname, str(now), msg), ))

if __name__ == '__main__':
    unittest.main()
