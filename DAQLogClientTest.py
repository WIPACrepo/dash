#!/usr/bin/env python

import os, tempfile, time, unittest
from DAQLogClient import FileAppender

class TestDAQLogClient(unittest.TestCase):
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
        self.collector = None

        TestDAQLogClient.DIR_PATH = tempfile.mkdtemp()

    def tearDown(self):
        if self.collector is not None:
            self.collector.close()

        time.sleep(0.1)

        for root, dirs, files in os.walk(TestDAQLogClient.DIR_PATH,
                                         topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(TestDAQLogClient.DIR_PATH)
        TestDAQLogClient.DIR_PATH = None

    def testDAQLogClient(self):
        logName = 'foo'
        logPath = os.path.join(TestDAQLogClient.DIR_PATH, "dash.log")

        self.collector = FileAppender(logName, logPath)

        self.failUnless(os.path.exists(logPath), 'Log file was not created')

        msg = 'Test msg'

        self.collector.write(msg)

        self.collector.close()

        lines = self.readLog(logPath)
        self.assertEquals(1, len(lines), 'Expected 1 line, not %d' % len(lines))

        prefix = logName + ' ['

        line = lines[0].rstrip()
        self.failUnless(line.startswith(prefix),
                        'Log entry "%s" should start with "%s"' %
                        (line, prefix))
        self.failUnless(line.endswith('] ' + msg),
                        'Log entry "%s" should start with "%s"' %
                        (line, '] ' + msg))

    def testDAQLogClientBadPath(self):
        logName = 'foo'
        badPath = os.path.join('a', 'bad', 'path')
        while os.path.exists(badPath):
            badPath = os.path.join(badPath, 'x')

        self.assertRaises(Exception, FileAppender, logName, badPath)

if __name__ == '__main__':
    unittest.main()
