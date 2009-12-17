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

                if not cDict.has_key(conn.type):
                    cDict[conn.type] = ConnTypeEntry(conn.type)
                cDict[conn.type].add(conn, comp)

        return cDict

    def testConnector(self):
        typeStr = 'abc'
        port = 123

        for isInput in (False, True):
            conn = Connector(typeStr, isInput, port)
            if isInput:
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

        conn = Connector(connType, True, connPort)

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
        inputs = (('Start', 1, 'here', ('Conn1', False, None)),
                  ('Middle', 2, 'neither', ('Conn1', True, 123),
                   ('Conn2', False, None)),
                  ('Finish', 3, 'there', ('Conn2', True, 456)))

        entries = self.connect(inputs)

        cMap = {}
        for key in entries.keys():
            entries[key].buildConnectionMap(cMap)

        for key in cMap.keys():
            print str(key) + ':'
            for entry in cMap[key]:
                print '  ' + str(entry)

if __name__ == '__main__':
    unittest.main()
