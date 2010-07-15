#!/usr/bin/env python

import unittest
from CnCServer import ConnTypeEntry, Connection, Connector

from DAQMocks import MockComponent

class TestCnCMisc(unittest.TestCase):

    def checkConnectionMap(self, expVal, cMap, key):
        self.assertEquals(expVal, cMap[key], 'Expected %s "%s", not "%s"' %
                          (key, str(expVal), str(cMap[key])))

    def connect(self, inputs):
        cDict = {}
        for data in inputs:
            comp = MockComponent(data[0], data[1], data[2])
            for cData in data[3:]:
                conn = Connector(cData[0], cData[1], cData[2])

                if not cDict.has_key(conn.name()):
                    cDict[conn.name()] = ConnTypeEntry(conn.name())
                cDict[conn.name()].add(conn, comp)

        return cDict

    def testConnector(self):
        typeStr = 'abc'
        port = 123

        for descrCh in (Connector.OUTPUT, Connector.INPUT):
            conn = Connector(typeStr, descrCh, port)
            if descrCh == Connector.INPUT:
                expStr = '%d=>%s' % (port, typeStr)
            else:
                expStr = '%s=>' % typeStr
            self.assertEquals(expStr, str(conn),
                              'Expected "%s", not "%s"' % (expStr, str(conn)))

    def testConnection(self):
        compName = 'abc'
        compId = 123
        compHost = 'foo'

        comp = MockComponent(compName, compId, compHost)

        connType = 'xyz'
        connPort = 987

        conn = Connector(connType, Connector.INPUT, connPort)

        ctn = Connection(conn, comp)

        expStr = '%s:%s#%d@%s:%d' % (connType, compName, compId, compHost,
                                     connPort)
        self.assertEquals(expStr, str(ctn),
                          'Expected "%s", not "%s"' % (expStr, str(ctn)))

        cMap = ctn.map()
        self.checkConnectionMap(connType, cMap, 'type')
        self.checkConnectionMap(compName, cMap, 'compName')
        self.checkConnectionMap(compId, cMap, 'compNum')
        self.checkConnectionMap(compHost, cMap, 'host')
        self.checkConnectionMap(connPort, cMap, 'port')

    def testConnTypeEntrySimple(self):
        inputs = (('Start', 1, 'here', ('Conn1', Connector.OUTPUT, None)),
                  ('Middle', 2, 'neither', ('Conn1', Connector.INPUT, 123),
                   ('Conn2', Connector.OUTPUT, None)),
                  ('Finish', 3, 'there', ('Conn2', Connector.INPUT, 456)))

        entries = self.connect(inputs)

        cMap = {}
        for key in entries.keys():
            entries[key].buildConnectionMap(cMap)

        for key in cMap.keys():
            print str(key) + ':'
            for entry in cMap[key]:
                print '  ' + str(entry)

    def testConnTypeEntryOptional(self):
        inputs = (('Start', 1, 'here',
                   ('ReqReq', Connector.OUTPUT, None),
                   ('OptOpt', Connector.OPT_OUTPUT, None),
                   ('OptNone', Connector.OPT_INPUT, 9999)),
                  ('Middle', 2, 'somewhere',
                   ('ReqReq', Connector.INPUT, 1001),
                   ('OptOpt', Connector.OPT_INPUT, 1002),
                   ('OptReq', Connector.OUTPUT, None),
                   ('ReqOpt', Connector.OPT_OUTPUT, None)),
                  ('Finish', 3, 'there',
                   ('OptReq', Connector.INPUT, 2001),
                   ('ReqOpt', Connector.OPT_INPUT, 2002),
                   ('NoneOpt', Connector.OPT_OUTPUT, None)))

        entries = self.connect(inputs)

        cMap = {}
        for key in entries.keys():
            entries[key].buildConnectionMap(cMap)

        expMap = {}
        for i in range(2):
            key = "%s#%d" % (inputs[i][0], inputs[i][1])
            expMap[key] = {}
            for conn in inputs[i][3:]:
                if conn[0].find("None") < 0 and \
                   (conn[1] == Connector.OUTPUT or \
                    conn[1] == Connector.OPT_OUTPUT):
                    expMap[key][conn[0]] = "%s#%d" % \
                                           (inputs[i + 1][0], inputs[i + 1][1])

        for comp in cMap.keys():
            key = str(comp)
            if not expMap.has_key(key):
                self.fail("Unexpected connection map entry for \"%s\"" % key)
            for entry in cMap[comp]:
                entryMap = entry.map()

                conn = entryMap["type"]
                comp = "%s#%d" % (entryMap["compName"], entryMap["compNum"])

                if not expMap[key].has_key(conn):
                    self.fail(("Component \"%s\" should not have a \"%s\"" +
                               " connection") % (key, conn))

                xComp = expMap[key][conn]
                self.assertEquals(xComp, comp,
                                  ("Expected \"%s\" type \"%s\" to connect to" +
                                   " %s, not %s") % (key, conn, xComp, comp))

if __name__ == '__main__':
    unittest.main()
