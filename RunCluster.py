#!/usr/bin/env python

from __future__ import print_function

import os
import os.path
import traceback

from CachedConfigName import CachedConfigName
from ClusterDescription import ClusterDescription, HSArgs, HubComponent, \
    JVMArgs, ReplayHubComponent
from DefaultDomGeometry import DefaultDomGeometry
from i3helper import Comparable


class RunClusterError(Exception):
    "Base exception for this package"
    pass


class RunNode(Comparable):
    "An entry from the cluster configuration"
    def __init__(self, hostname, default_hs_dir, default_hs_ival,
                 default_hs_max_files, default_jvm_path, default_jvm_server,
                 default_jvm_heap_init, default_jvm_heap_max, default_jvm_args,
                 default_jvm_extra_args, default_log_level):
        self.__loc_name = hostname
        self.__hostname = hostname
        self.__default_hs = HSArgs(default_hs_dir, default_hs_ival,
                                   default_hs_max_files)
        self.__default_jvm = JVMArgs(default_jvm_path, default_jvm_server,
                                     default_jvm_heap_init,
                                     default_jvm_heap_max,
                                     default_jvm_args, default_jvm_extra_args)
        self.__default_log_level = default_log_level
        self.__comps = []

    def __cmp__(self, other):
        val = cmp(self.hostname, other.hostname)
        if val == 0:
            val = cmp(self.location, other.location)
        return val

    def __str__(self):
        return "%s(%s)*%d" % (self.__hostname, self.__default_log_level,
                              len(self.__comps))

    def add_component(self, comp):
        comp.host = self.__hostname
        self.__comps.append(comp)

    @property
    def compare_tuple(self):
        return (self.__hostname, self.__loc_name)

    def components(self):
        return self.__comps[:]

    @property
    def default_log_level(self):
        return self.__default_log_level

    @property
    def hostname(self):
        return self.__hostname

    @property
    def location(self):
        return self.__loc_name


class SimAlloc(object):
    "Temporary class used to assign simulated hubs to hosts"
    def __init__(self, comp):
        self.__comp = comp
        self.__number = 0
        self.__percent = 0.0

        self.__allocated = 0

    def __lt__(self, other):
        if self.allocated < other.allocated:
            return True

        if self.allocated == other.allocated and \
             self.host > other.host:
            return True

        return False

    def __str__(self):
        return "%s#%d%%%.2f=%d" % (self.__comp.host, self.__number,
                                   self.__percent, self.__allocated)

    def add(self, comp):
        self.__number += comp.number

        pct = (10.0 / float(comp.priority)) * float(comp.number)
        self.__percent += pct
        return pct

    def adjust_percentage(self, pct_tot, num_hubs):
        self.__percent /= pct_tot
        self.__allocated = int(self.__percent * num_hubs)
        if self.__allocated > self.__number:
            # if we overallocated based on the percentage,
            #  adjust down to the maximum number
            self.__allocated = self.__number
        return self.__allocated

    def allocate_one(self):
        if self.__allocated >= self.__number:
            return False
        self.__allocated += 1
        return True

    @property
    def allocated(self):
        return self.__allocated

    @property
    def host(self):
        return self.__comp.host

    @property
    def percent(self):
        return self.__percent


class RunCluster(CachedConfigName):
    "Cluster->component mapping generated from a run configuration file"
    def __init__(self, cfg, descrName=None, config_dir=None):
        "Create a cluster->component mapping from a run configuration file"
        super(RunCluster, self).__init__()

        self.__hub_list = self.__extract_hubs(cfg)

        self.__cluster_desc = ClusterDescription(config_dir, descrName)

        # set the name to the run config plus cluster config
        name = os.path.basename(cfg.fullpath)
        if name.endswith('.xml'):
            name = name[:-4]
        if self.__cluster_desc.name != "sps" and \
           self.__cluster_desc.name != "spts":
            name += "@" + self.__cluster_desc.name
        self.set_name(name)

        self.__nodes = self.__build_node_map(self.__cluster_desc,
                                             self.__hub_list, cfg)

    def __str__(self):
        node_str = ""
        for node in self.__nodes:
            if node_str != "":
                node_str += " "
            node_str += "%s*%d" % (node.hostname, len(node.components()))
        return self.config_name + "[" + node_str + "]"

    @classmethod
    def __add_component(cls, host_map, host, comp):
        "Add a component to the host_map dictionary"
        if host not in host_map:
            host_map[host] = {}
        host_map[host][str(comp)] = comp

    @classmethod
    def __add_real_hubs(cls, cluster_desc, hub_list, host_map):
        "Add hubs with hard-coded locations to host_map"
        for (host, comp) in cluster_desc.host_component_pairs:
            if not comp.is_hub:
                continue
            for idx in range(0, len(hub_list)):
                if comp.id == hub_list[idx].id:
                    cls.__add_component(host_map, host, comp)
                    del hub_list[idx]
                    break

    @classmethod
    def __add_replay_hubs(cls, cluster_desc, hub_list, host_map, run_cfg):
        """
        Add replay hubs with locations hard-coded in the run config to host_map
        """

        hs_dir = cluster_desc.default_hs_directory("StringHub")
        hs_ival = cluster_desc.default_hs_interval("StringHub")
        hs_max_files = cluster_desc.default_hs_max_files("StringHub")

        jvm_path = cluster_desc.default_jvm_path("StringHub")
        jvm_server = cluster_desc.default_jvm_server("StringHub")
        jvm_heap_init = cluster_desc.default_jvm_heap_init("StringHub")
        jvm_heap_max = cluster_desc.default_jvm_heap_max("StringHub")
        jvm_args = cluster_desc.default_jvm_args("StringHub")
        jvm_extra = cluster_desc.default_jvm_extra_args("StringHub")

        #alert_email = cluster_desc.default_alert_email("StringHub")
        #ntp_host = cluster_desc.default_ntp_host("StringHub")

        log_level = cluster_desc.default_log_level("StringHub")

        if run_cfg is None:
            num_to_skip = None
        else:
            num_to_skip = run_cfg.num_replay_files_to_skip

        i = 0
        while i < len(hub_list):
            hub = hub_list[i]
            if hub.host is None:
                i += 1
                continue

            # die if host was not found in cluster config
            if cluster_desc.host(hub.host) is None:
                raise RunClusterError("Cannot find %s for replay in %s" %
                                      (hub.host, cluster_desc.name))

            if hub.log_level is not None:
                lvl = hub.log_level
            else:
                lvl = log_level

            comp = ReplayHubComponent(hub.name, hub.id, lvl, False)
            comp.host = hub.host

            comp.set_jvm_options(None, jvm_path, jvm_server, jvm_heap_init,
                                 jvm_heap_max, jvm_args, jvm_extra)
            comp.set_hit_spool_options(None, hs_dir, hs_ival, hs_max_files)

            if num_to_skip is not None and num_to_skip > 0:
                comp.num_replay_files_to_skip = num_to_skip

            cls.__add_component(host_map, comp.host, comp)
            del hub_list[i]

    @classmethod
    def __add_required(cls, cluster_desc, host_map):
        "Add required components to host_map"
        for (host, comp) in cluster_desc.host_component_pairs:
            if comp.required:
                cls.__add_component(host_map, host, comp)

    @classmethod
    def __add_sim_hubs(cls, cluster_desc, hub_list, host_map):
        "Add simulated hubs to host_map"
        sim_list = cls.__get_sorted_sim_hubs(cluster_desc, host_map)
        if len(sim_list) == 0:
            missing = []
            for hub in hub_list:
                missing.append(str(hub))
            raise RunClusterError("Cannot simulate %s hubs %s" %
                                  (cluster_desc.name, str(missing)))

        hub_alloc = {}
        max_hubs = 0
        pct_tot = 0.0
        for sim in sim_list:
            if sim.host not in hub_alloc:
                # create new host entry
                hub_alloc[sim.host] = SimAlloc(sim)

            # add to the maximum number of hubs for this host
            pct = hub_alloc[sim.host].add(sim)

            max_hubs += sim.number
            pct_tot += pct

        # make sure there's enough room for the requested hubs
        num_hubs = len(hub_list)
        if num_hubs > max_hubs:
            raise RunClusterError("Only have space for %d of %d hubs" %
                                  (max_hubs, num_hubs))

        # first stab at allocation: allocate based on percentage
        tot = 0
        for hub in list(hub_alloc.values()):
            tot += hub.adjust_percentage(pct_tot, num_hubs)

        # allocate remainder in order of total capacity
        while tot < num_hubs:
            changed = False
            for hub in sorted(list(hub_alloc.values()), reverse=True):
                if hub.allocate_one():
                    tot += 1
                    changed = True
                    if tot >= num_hubs:
                        break

            if tot < num_hubs and not changed:
                raise RunClusterError("Only able to allocate %d of %d hubs" %
                                      (tot, num_hubs))

        hub_list.sort()

        hosts = []
        for hub in sorted(list(hub_alloc.values()), reverse=True):
            hosts.append(hub.host)

        jvm_path = cluster_desc.default_jvm_path("StringHub")
        jvm_server = cluster_desc.default_jvm_server("StringHub")
        jvm_heap_init = cluster_desc.default_jvm_heap_init("StringHub")
        jvm_heap_max = cluster_desc.default_jvm_heap_max("StringHub")
        jvm_args = cluster_desc.default_jvm_args("StringHub")
        jvm_extra = cluster_desc.default_jvm_extra_args("StringHub")

        log_level = cluster_desc.default_log_level("StringHub")

        if False:
            print()
            print("======= SimList")
            for sim in sim_list:
                print(":: %s<%s>" % (sim, type(sim)))
            print("======= HubList")
            for hub in hub_list:
                print(":: %s<%s>" % (hub, type(hub)))

        hub_num = 0
        for host in hosts:
            for _ in range(hub_alloc[host].allocated):
                hub_comp = hub_list[hub_num]
                if hub_comp.log_level is not None:
                    lvl = hub_comp.log_level
                else:
                    lvl = log_level

                comp = HubComponent(hub_comp.name, hub_comp.id, lvl, False)
                comp.host = host

                comp.set_jvm_options(None, jvm_path, jvm_server, jvm_heap_init,
                                     jvm_heap_max, jvm_args, jvm_extra)
                comp.set_hit_spool_options(None, None, None, None)

                cls.__add_component(host_map, host.name, comp)
                hub_num += 1

    @classmethod
    def __add_triggers(cls, cluster_desc, hub_list, host_map):
        "Add needed triggers to host_map"
        need_amanda = False
        need_inice = False
        need_icetop = False

        for hub in hub_list:
            hid = hub.id % 1000
            if hid == 0:
                need_amanda = True
            elif hid < 200:
                need_inice = True
            else:
                need_icetop = True

        for (host, comp) in cluster_desc.host_component_pairs:
            if not comp.name.endswith('Trigger'):
                continue
            if comp.name == 'amandaTrigger' and need_amanda:
                cls.__add_component(host_map, host, comp)
                need_amanda = False
            elif comp.name == 'inIceTrigger' and need_inice:
                cls.__add_component(host_map, host, comp)
                need_inice = False
            elif comp.name == 'iceTopTrigger' and need_icetop:
                cls.__add_component(host_map, host, comp)
                need_icetop = False

    @classmethod
    def __convert_to_nodes(cls, cluster_desc, host_map):
        "Convert host_map to an array of cluster nodes"
        nodes = []
        for host in sorted(host_map.keys()):
            node = RunNode(str(host),
                           cluster_desc.default_hs_directory(),
                           cluster_desc.default_hs_interval(),
                           cluster_desc.default_hs_max_files(),
                           cluster_desc.default_jvm_path(),
                           cluster_desc.default_jvm_server(),
                           cluster_desc.default_jvm_heap_init(),
                           cluster_desc.default_jvm_heap_max(),
                           cluster_desc.default_jvm_args(),
                           cluster_desc.default_jvm_extra_args(),
                           cluster_desc.default_log_level())
            nodes.append(node)

            for key in host_map[host].keys():
                node.add_component(host_map[host][key])

        return nodes

    @classmethod
    def __extract_hubs(cls, runcfg):
        "build a list of hub components used by the run configuration"
        hub_list = []
        for comp in runcfg.components():
            if comp.is_hub:
                hub_list.append(comp)
        return hub_list

    @classmethod
    def __get_sorted_sim_hubs(cls, cluster_desc, host_map):
        "Get list of simulation hubs, sorted by priority"
        sim_list = []

        for (_, sim_hub) in cluster_desc.host_sim_hub_pairs:
            if sim_hub is None:
                continue
            if not sim_hub.if_unused or sim_hub.host.name not in host_map:
                sim_list.append(sim_hub)

        sim_list.sort(key=lambda x: x.priority)

        return sim_list

    @classmethod
    def __build_node_map(cls, cluster_desc, hub_list, run_cfg):
        host_map = {}

        cls.__add_required(cluster_desc, host_map)
        cls.__add_triggers(cluster_desc, hub_list, host_map)
        if len(hub_list) > 0:
            cls.__add_real_hubs(cluster_desc, hub_list, host_map)
            if len(hub_list) > 0:
                cls.__add_replay_hubs(cluster_desc, hub_list, host_map,
                                      run_cfg)
                if len(hub_list) > 0:
                    cls.__add_sim_hubs(cluster_desc, hub_list, host_map)

        return cls.__convert_to_nodes(cluster_desc, host_map)

    @property
    def daq_data_dir(self):
        "Return the path to the directory where payload data is written"
        return self.__cluster_desc.daq_data_dir

    @property
    def daq_log_dir(self):
        """
        Return the path to the directory where pDAQ log/moni files are written
        """
        return self.__cluster_desc.daq_log_dir

    @property
    def default_log_level(self):
        "Return the default log level"
        return self.__cluster_desc.default_log_level()

    @property
    def description(self):
        "Return the name of this cluster description"
        return self.__cluster_desc.config_name

    def extract_components(self, master_list):
        """
        Extract all nodes which match names in 'master_list'.
        Return a tuple containing a list of the matched nodes and a list
        of names which could not be found
        """
        return self.extract_components_from_nodes(self.__nodes, master_list)

    @classmethod
    def extract_components_from_nodes(cls, node_list, master_list):
        """
        Extract all nodes which match names in 'master_list'.
        Return a tuple containing a list of the matched nodes and a list
        of names which could not be found
        """
        found_list = []
        missing_list = []
        for comp in master_list:
            found = False
            for node in node_list:
                for node_comp in node.components():
                    if comp.name.lower() == node_comp.name.lower() \
                       and comp.num == node_comp.id:
                        found_list.append(node_comp)
                        found = True
                        break
                if found:
                    break
            if not found:
                missing_list.append(comp)
        return (found_list, missing_list)

    def get_hub_nodes(self):
        "Get a list of nodes on which hub components are running"
        host_map = {}
        for node in self.__nodes:
            add_host = False
            for comp in node.components():
                if comp.is_hub:
                    add_host = True
                    break

            if add_host:
                host_map[node.hostname] = 1

        return list(host_map.keys())

    def load_if_changed(self, run_config=None, new_path=None):
        "If the cluster description file has been modified, reload it"
        if not self.__cluster_desc.load_if_changed(new_path=new_path):
            return False

        if run_config is not None:
            self.__hub_list = self.__extract_hubs(run_config)

        self.__nodes = self.__build_node_map(self.__cluster_desc,
                                             self.__hub_list, run_config)
        return True

    @property
    def log_dir_for_spade(self):
        "Return the path to JADE's 'dropbox' directory"
        return self.__cluster_desc.log_dir_for_spade

    @property
    def log_dir_copies(self):
        "Return the path to the directory holding copies of the pDAQ logs"
        return self.__cluster_desc.log_dir_copies

    def nodes(self):
        "Return the entries in this cluster"
        return self.__nodes[:]


def main():
    "Main program"
    import sys

    from DAQConfig import DAQConfigParser
    from locate_pdaq import find_pdaq_config

    if len(sys.argv) <= 1:
        raise SystemExit('Usage: %s [-C clusterDescription] configXML'
                         ' [configXML ...]' % sys.argv[0])

    pdaq_dir = find_pdaq_config()
    if pdaq_dir is None or pdaq_dir == "":
        raise SystemExit("Cannot find pDAQ configuration directory")

    name_list = []
    grab_desc = False
    cluster_desc = None

    for name in sys.argv[1:]:
        if grab_desc:
            cluster_desc = name
            grab_desc = False
            continue

        if name.startswith('-C'):
            if cluster_desc is not None:
                raise Exception("Cannot specify multiple cluster descriptions")
            if len(name) > 2:
                cluster_desc = name[2:]
            else:
                grab_desc = True
            continue

        if os.path.basename(name) == DefaultDomGeometry.FILENAME:
            # ignore
            continue

        name_list.append(name)

    for name in name_list:
        (ndir, nbase) = os.path.split(name)
        if ndir is None or ndir == "":
            config_dir = pdaq_dir
        else:
            config_dir = ndir
        cfg = DAQConfigParser.parse(config_dir, nbase)
        try:
            run_cluster = RunCluster(cfg, cluster_desc)
        except NotImplementedError:
            print('For %s:' % name, file=sys.stderr)
            traceback.print_exc()
            continue
        except KeyboardInterrupt:
            break
        except:
            print('For %s:' % name, file=sys.stderr)
            traceback.print_exc()
            continue

        print('RunCluster: %s (%s)' % \
            (run_cluster.config_name, run_cluster.description))
        print('--------------------')
        if run_cluster.log_dir_for_spade is not None:
            print('SPADE logDir: %s' % run_cluster.log_dir_for_spade)
        if run_cluster.log_dir_copies is not None:
            print('Copied logDir: %s' % run_cluster.log_dir_copies)
        if run_cluster.daq_data_dir is not None:
            print('DAQ dataDir: %s' % run_cluster.daq_data_dir)
        if run_cluster.daq_log_dir is not None:
            print('DAQ logDir: %s' % run_cluster.daq_log_dir)
        print('Default log level: %s' % run_cluster.default_log_level)
        for node in run_cluster.nodes():
            print('  %s@%s logLevel %s' % \
                (node.location, node.hostname, node.default_log_level))
            comps = sorted(node.components())
            for comp in comps:
                print('    %s %s' % (comp, comp.log_level))


if __name__ == '__main__':
    main()
