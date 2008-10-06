#!/usr/bin/env python

import os, tempfile, time, unittest
from DAQLog import SocketLogger, logCollector
from DAQLogClient import DAQLogger

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
        self.collector = None

        TestDAQLog.DIR_PATH = tempfile.mkdtemp()

    def tearDown(self):
        if self.sockLog is not None:
            self.sockLog.stopServing()
        if self.collector is not None:
            self.collector.close()

        time.sleep(0.1)

        for root, dirs, files in os.walk(TestDAQLog.DIR_PATH, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(TestDAQLog.DIR_PATH)
        TestDAQLog.DIR_PATH = None

    def testSocketLogger(self):
        port = 5432
        cname = 'foo'
        logPath = os.path.join(TestDAQLog.DIR_PATH, 'foo.log')

        self.sockLog = SocketLogger(port, cname, logPath, True)
        self.sockLog.startServing()
        self.failUnless(os.path.exists(logPath), 'Log file was not created')

        msg = 'Test 1 2 3'

        client = DAQLogger('localhost', port)
        client.write(msg)

        client.close()

        self.sockLog.stopServing()

        self.checkLog(logPath, (cname + ' ' + msg, ))

    def testLogCollector(self):
        runNum = 123

        self.collector = logCollector(runNum, TestDAQLog.DIR_PATH)

        midDir = logCollector.logDirName(runNum)

        logPath = '%s/%s/dash.log' % (TestDAQLog.DIR_PATH, midDir)

        self.failUnless(os.path.exists(logPath), 'Log file was not created')

        msg = 'Test msg'

        self.collector.dashLog(msg)

        self.collector.close()

        lines = self.readLog(logPath)
        self.assertEquals(1, len(lines), 'Expected 1 line, not %d' % len(lines))

        prefix = 'DAQRun ['

        line = lines[0].rstrip()
        self.failUnless(line.startswith(prefix),
                        'Log entry "%s" should start with "%s"' %
                        (line, prefix))
        self.failUnless(line.endswith('] ' + msg),
                        'Log entry "%s" should start with "%s"' %
                        (line, '] ' + msg))

    def testLogCollectorTwice(self):
        runNum = 123

        self.collector = logCollector(runNum, TestDAQLog.DIR_PATH)

        midDir = logCollector.logDirName(runNum)

        logPath = '%s/%s/dash.log' % (TestDAQLog.DIR_PATH, midDir)

        self.failUnless(os.path.exists(logPath), 'Log file was not created')

        self.collector.close()

        self.collector = logCollector(runNum, TestDAQLog.DIR_PATH)

        oldPath = '%s/old_%s_00/dash.log' % (TestDAQLog.DIR_PATH, midDir)

        self.failUnless(os.path.exists(oldPath), 'Old file was not created')

if __name__ == '__main__':
    unittest.main()
