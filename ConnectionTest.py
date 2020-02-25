#!/usr/bin/env python

from __future__ import print_function

import shutil
import tempfile
import unittest
from CnCServer import Connector, DAQPool

from DAQMocks import MockDAQClient, MockLogger, MockRunConfigFile

LOUD = False


class MyDAQPool(DAQPool):
    def get_cluster_config(self, run_config=None):
        raise NotImplementedError("Unimplemented")

    def return_runset_components(self, runset, verbose=False, kill_with_9=True,
                                 event_check=False):
        runset.return_components(self, None, None, None, verbose=verbose,
                                 kill_with_9=kill_with_9,
                                 event_check=event_check)


class Node(object):
    IS_OUTPUT = True
    IS_INPUT = False

    CONN_PORT = -1

    def __init__(self, name, num=0):
        self.name = name
        self.num = num
        self.out_links = {}
        self.in_links = {}

    def __str__(self):
        return self.name + '#' + str(self.num)

    def connect_output_to(self, comp, io_type):
        self.link(comp, io_type, Node.IS_OUTPUT)
        comp.link(self, io_type, Node.IS_INPUT)

    @property
    def connections(self):
        connectors = []
        for key in list(self.out_links.keys()):
            connectors.append(Connector(key, Connector.OUTPUT, self.next_port))
        for key in list(self.in_links.keys()):
            connectors.append(Connector(key, Connector.INPUT, self.next_port))
        return connectors

    @property
    def next_port(self):
        port = Node.CONN_PORT
        Node.CONN_PORT -= 1
        return port

    def link(self, comp, io_type, is_output):
        if is_output:
            links = self.out_links
        else:
            links = self.in_links

        if io_type not in links:
            links[io_type] = []

        links[io_type].append(comp)


class ConnectionTest(unittest.TestCase):
    EXP_ID = 1

    def __build_runset(self, node_list, extra_loud=True):
        if LOUD:
            print('-- Nodes')
            for node in node_list:
                print(node.getDescription())

        node_log = {}

        pool = MyDAQPool()
        port = -1
        for node in node_list:
            key = '%s#%d' % (node.name, node.num)
            node_log[key] = MockLogger('Log-%s' % key)
            pool.add(MockDAQClient(node.name, node.num, None, port, 0,
                                   node.connections, node_log[key],
                                   node.out_links, extra_loud=extra_loud))
            port -= 1
        self.assertEqual(pool.num_components, len(node_list))

        if LOUD:
            print('-- Pool has %s comps' % pool.num_components)
            for comp in pool.components:
                print('    %s' % str(comp))

        num_comps = pool.num_components

        name_list = []
        for node in node_list:
            name_list.append(node.name + '#' + str(node.num))

        rc_file = MockRunConfigFile(self.__run_config_dir)
        run_config = rc_file.create(name_list, {})

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_regexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = pool.make_runset(self.__run_config_dir, run_config, 0, 0,
                                  logger, daq_data_dir, force_restart=False,
                                  strict=False)

        chk_id = ConnectionTest.EXP_ID
        ConnectionTest.EXP_ID += 1

        self.assertEqual(pool.num_unused, 0)
        self.assertEqual(pool.num_sets, 1)
        self.assertEqual(pool.runset(0), runset)

        self.assertEqual(runset.id, chk_id)
        self.assertEqual(runset.size(), len(node_list))

        # copy node list
        #
        tmp_list = node_list[:]

        # validate all components in runset
        #
        for comp in runset.components:
            node = None
            for tmp in tmp_list:
                if comp.name == tmp.name and comp.num == tmp.num:
                    node = tmp
                    tmp_list.remove(tmp)
                    break

            self.assertFalse(not node,
                             "Could not find component " + str(comp))

            # copy connector list
            #
            comp_conn = comp.connectors()

            # remove all output connectors
            #
            for typ in node.out_links:
                conn = None
                for tmp in comp_conn:
                    if not tmp.is_input and tmp.name == typ:
                        conn = tmp
                        comp_conn.remove(tmp)
                        break

                self.assertFalse(not conn, "Could not find connector " + typ +
                                 " for component " + str(comp))

            # remove all input connectors
            #
            for typ in node.in_links:
                conn = None
                for tmp in comp_conn:
                    if tmp.is_input and tmp.name == typ:
                        conn = tmp
                        comp_conn.remove(tmp)
                        break

                self.assertFalse(not conn, "Could not find connector " + typ +
                                 " for component " + str(comp))

            # whine if any connectors are left
            #
            self.assertEqual(len(comp_conn), 0, 'Found extra connectors in ' +
                             str(comp_conn))

        # whine if any components are left
        #
        self.assertEqual(len(tmp_list), 0, 'Found extra components in ' +
                         str(tmp_list))

        if LOUD:
            print('-- SET: ' + str(runset))

        if extra_loud:
            for key in node_log:
                node_log[key].add_expected_exact('End of log')
                node_log[key].add_expected_exact('Reset log to ?LOG?')
        pool.return_runset(runset, logger)
        self.assertEqual(pool.num_components, num_comps)
        self.assertEqual(pool.num_sets, 0)

        logger.check_status(10)

        for key in node_log:
            node_log[key].check_status(10)

    def setUp(self):
        self.__run_config_dir = tempfile.mkdtemp()

    def tearDown(self):
        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)

    def test_simple(self):
        # build nodes
        #
        n1a = Node('oneA')
        n1b = Node('oneB')
        n20 = Node('two')
        n30 = Node('three')
        n40 = Node('four')

        # connect nodes
        #
        n1a.connect_output_to(n20, 'out1')
        n1b.connect_output_to(n20, 'out1')
        n20.connect_output_to(n30, 'out2')
        n30.connect_output_to(n40, 'out3')

        # build list of all nodes
        #
        all_nodes = [n1a, n1b, n20, n30, n40]

        self.__build_runset(all_nodes)

    def test_standard(self):
        # build nodes
        #
        sh_list = []
        ih_list = []

        for idx in range(0, 4):
            sh_list.append(Node('StringHub', idx + 10))
            ih_list.append(Node('IcetopHub', idx + 20))

        gtrig = Node('GlobalTrigger')
        iitrig = Node('InIceTrigger')
        ittrig = Node('IceTopTrigger')
        ebldr = Node('EventBuilder')

        # connect in-ice hubs
        for shub in sh_list:
            shub.connect_output_to(iitrig, 'stringHit')
            ebldr.connect_output_to(shub, 'rdoutReq')
            shub.connect_output_to(ebldr, 'rdoutData')

        # connect icetop hubs
        for ihub in ih_list:
            ihub.connect_output_to(ittrig, 'icetopHit')
            ebldr.connect_output_to(ihub, 'rdoutReq')
            ihub.connect_output_to(ebldr, 'rdoutData')

        iitrig.connect_output_to(gtrig, 'inIceTrigger')
        ittrig.connect_output_to(gtrig, 'iceTopTrigger')

        gtrig.connect_output_to(ebldr, 'glblTrigger')

        # build list of all nodes
        #
        all_nodes = [gtrig, iitrig, ittrig, ebldr]
        for i in sh_list:
            all_nodes.append(i)
        for i in ih_list:
            all_nodes.append(i)

        self.__build_runset(all_nodes)

    def test_complex(self):
        # build nodes
        #
        na1 = Node('A', 1)
        na2 = Node('A', 2)
        nb1 = Node('B', 1)
        nb2 = Node('B', 2)
        nc0 = Node('C')
        nd0 = Node('D')
        ne0 = Node('E')
        nf0 = Node('F')
        ng0 = Node('G')
        nh0 = Node('H')
        ni0 = Node('I')

        # connect nodes
        #
        na1.connect_output_to(nc0, 'DataA')
        na2.connect_output_to(nc0, 'DataA')
        nb1.connect_output_to(nd0, 'DataB')
        nb2.connect_output_to(nd0, 'DataB')

        nc0.connect_output_to(ne0, 'DataC')
        nd0.connect_output_to(nf0, 'DataD')
        ne0.connect_output_to(nf0, 'DataE')
        nf0.connect_output_to(ng0, 'DataF')
        ng0.connect_output_to(nh0, 'DataG')
        nh0.connect_output_to(ne0, 'BackH')
        nh0.connect_output_to(ni0, 'DataH')

        # build list of all nodes
        #
        all_nodes = [na1, na2, nb1, nb2, nc0, nd0, ne0, nf0, ng0, nh0, ni0]

        self.__build_runset(all_nodes)


if __name__ == '__main__':
    unittest.main()
