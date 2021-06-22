#!/usr/bin/env python

from __future__ import print_function

import unittest
from CnCServer import Connector
from RunSet import ConnTypeEntry, Connection

from DAQMocks import MockComponent


class TestCnCMisc(unittest.TestCase):

    def check_connection_map(self, exp_val, cmap, key):
        self.assertEqual(exp_val, cmap[key], 'Expected %s "%s", not "%s"' %
                         (key, str(exp_val), str(cmap[key])))

    @classmethod
    def connect(cls, inputs):
        cdict = {}
        for data in inputs:
            comp = MockComponent(data[0], data[1], data[2])
            for cdata in data[3:]:
                conn = Connector(cdata[0], cdata[1], cdata[2])

                if conn.name not in cdict:
                    cdict[conn.name] = ConnTypeEntry(conn.name)
                cdict[conn.name].add(conn, comp)

        return cdict

    def test_connector(self):
        type_str = 'abc'
        port = 123

        for descr_char in (Connector.OUTPUT, Connector.INPUT):
            conn = Connector(type_str, descr_char, port)
            if descr_char == Connector.INPUT:
                expstr = '%d=>%s' % (port, type_str)
            else:
                expstr = '%s=>' % type_str
            self.assertEqual(expstr, str(conn),
                             'Expected "%s", not "%s"' % (expstr, str(conn)))

    def test_connection(self):
        comp_name = 'abc'
        comp_id = 123
        comp_host = 'foo'

        comp = MockComponent(comp_name, comp_id, comp_host)

        conn_type = 'xyz'
        conn_port = 987

        conn = Connector(conn_type, Connector.INPUT, conn_port)

        ctn = Connection(conn, comp)

        expstr = '%s:%s#%d@%s:%d' % (conn_type, comp_name, comp_id, comp_host,
                                     conn_port)
        self.assertEqual(expstr, str(ctn),
                         'Expected "%s", not "%s"' % (expstr, str(ctn)))

        cmap = ctn.map()
        self.check_connection_map(conn_type, cmap, 'type')
        self.check_connection_map(comp_name, cmap, 'compName')
        self.check_connection_map(comp_id, cmap, 'compNum')
        self.check_connection_map(comp_host, cmap, 'host')
        self.check_connection_map(conn_port, cmap, 'port')

    def test_conn_type_entry_simple(self):
        inputs = (('Start', 1, 'here', ('Conn1', Connector.OUTPUT, None)),
                  ('Middle', 2, 'neither', ('Conn1', Connector.INPUT, 123),
                   ('Conn2', Connector.OUTPUT, None)),
                  ('Finish', 3, 'there', ('Conn2', Connector.INPUT, 456)))

        entries = self.connect(inputs)

        cmap = {}
        for key in list(entries.keys()):
            entries[key].build_connection_map(cmap)

        # for key in list(cmap.keys()):
        #     print(str(key) + ':')
        #     for entry in cmap[key]:
        #         print('  ' + str(entry))

    def test_conn_type_entry_optional(self):
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

        cmap = {}
        for key in list(entries.keys()):
            entries[key].build_connection_map(cmap)

        exp_map = {}
        for i in range(2):
            key = "%s#%d" % (inputs[i][0], inputs[i][1])
            exp_map[key] = {}
            for conn in inputs[i][3:]:
                if conn[1] == Connector.OUTPUT or \
                  conn[1] == Connector.OPT_OUTPUT:
                    if conn[0].find("None") < 0:
                        exp_map[key][conn[0]] = "%s#%d" % \
                          (inputs[i + 1][0], inputs[i + 1][1])

        for comp in list(cmap.keys()):
            key = str(comp)
            if key not in exp_map:
                self.fail("Unexpected connection map entry for \"%s\"" % key)
            for entry in cmap[comp]:
                entry_map = entry.map()

                conn = entry_map["type"]
                comp = "%s#%d" % (entry_map["compName"], entry_map["compNum"])

                if conn not in exp_map[key]:
                    self.fail(("Component \"%s\" should not have a \"%s\""
                               " connection") % (key, conn))

                xcomp = exp_map[key][conn]
                self.assertEqual(xcomp, comp,
                                 ("Expected \"%s\" type \"%s\" to connect to"
                                  " %s, not %s") % (key, conn, xcomp, comp))


if __name__ == '__main__':
    unittest.main()
