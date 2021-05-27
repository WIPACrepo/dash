#!/usr/bin/env python
"""
Main pDAQ daemon which manages pools of components and runsets
"""

from __future__ import print_function

import datetime
import numbers
import os
import signal
import socket
import sys
import threading
import time
import traceback

try:
    from SocketServer import ThreadingMixIn
except:  # ModuleNotFoundError only works under 2.7/3.0
    from socketserver import ThreadingMixIn

from CnCExceptions import CnCServerException, MissingComponentException, \
    StartInterruptedException
from CnCLogger import CnCLogger
from CompOp import ComponentGroup, OpClose, OpGetConnectionInfo, OpGetState, \
    OpResetComponent
from ComponentManager import ComponentManager
from DAQClient import ComponentName, DAQClient, DAQClientState
from DAQConfig import DAQConfigException, DAQConfigParser
from DAQConst import DAQPort
from DAQLive import DAQLive
from DAQLog import LogSocketServer
from DAQRPC import RPCClient, RPCServer
from Daemon import Daemon
from DumpThreads import DumpThreadsOnSignal
from ListOpenFiles import ListOpenFiles
from Process import find_python_process
from RunSet import RunSet
from RunSetState import RunSetState
from i3helper import reraise_excinfo
from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from scmversion import get_scmversion, get_scmversion_str
from xmlparser import XMLBadFileError
from utils import ip

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


# get location of pDAQ trunk
PDAQ_HOME = find_pdaq_trunk()


class DAQPool(object):
    "Pool of DAQClients and RunSets"

    def __init__(self):
        "Create an empty pool"
        self.__pool = {}
        self.__pool_lock = threading.RLock()

        self.__sets = []
        self.__sets_lock = threading.RLock()

        self.__starting = False

        super(DAQPool, self).__init__()

    def __add_to_pool(self, comp):
        "This method assumes that self.__pool_lock has already been acquired"
        if comp.name not in self.__pool:
            self.__pool[comp.name] = []
        for oldcomp in self.__pool[comp.name]:
            if comp.matches(oldcomp):
                return False

        self.__pool[comp.name].append(comp)
        return True

    def __add_known(self, needed, comp_list):
        wait_list = []
        for cobj in needed:
            found = False

            # are there any components with this name?
            if cobj.name not in self.__pool:
                has_entries = False
            else:
                plen = len(self.__pool[cobj.name])
                has_entries = plen > 0

            # if a component with this name has registered...
            if has_entries:
                for comp in self.__pool[cobj.name]:
                    # ...and it's the number we want and it's alive...
                    if comp.num == cobj.num and not comp.is_dying:
                        # grab the component from the pool
                        self.__pool[cobj.name].remove(comp)
                        pool_len = len(self.__pool[cobj.name])
                        if pool_len == 0:
                            # delete component list if this was the only entry
                            del self.__pool[cobj.name]

                        # add this component to the final list
                        comp_list.append(comp)
                        found = True
                        break

            if not found:
                wait_list.append(cobj)

        return wait_list

    def __add_runset(self, runset):
        with self.__sets_lock:
            self.__sets.append(runset)

    @classmethod
    def __build_comp_name_list(cls, namelist):
        """Build a list of ComponentNames from a list of name strings"""
        compnames = []
        for cname in namelist:
            pound = cname.rfind("#")
            if pound > 0:
                name = cname[0:pound]
                num = int(cname[pound + 1:])
            else:
                dash = cname.rfind("-")
                if dash > 0:
                    name = cname[0:dash]
                    num = int(cname[dash + 1:])
                else:
                    name = cname
                    num = 0
            compnames.append(ComponentName(name, num))
        return compnames

    def __collect_components(self, required_list, comp_list, logger, timeout):
        """
        Take all components in required_list from pool and add them to
        comp_list.
        Stop collecting if self.__starting is set to False.
        Return the list of any missing components if we time out.
        """
        needed = self.__build_comp_name_list(required_list)

        dt_timeout = datetime.timedelta(seconds=timeout)

        tstart = datetime.datetime.now()
        while self.__starting and \
          len(needed) > 0:  # pylint: disable=len-as-condition

            # add all known components, unknown components are left in 'needed'
            with self.__pool_lock:
                needed = self.__add_known(needed, comp_list)

            if len(needed) > 0:  # pylint: disable=len-as-condition
                if datetime.datetime.now() - tstart >= dt_timeout:
                    break

                logger.info("Waiting for %s" %
                            (ComponentManager.format_component_list(needed)), )
                time.sleep(5)

        if not self.__starting:
            raise StartInterruptedException("Collect interrupted")

        if len(needed) == 0:  # pylint: disable=len-as-condition
            return None
        return needed

    def __make_runset_internal(self, run_config_dir, run_config_name, run_num,
                               timeout, logger, daq_data_dir,
                               force_restart=True, strict=False):
        """
        Build a runset from the specified run configuration.
        If self.__starting is False, revert everything and raise an exception.
        If successful, return the runset.
        """
        logger.info("Loading run configuration \"%s\"" % run_config_name)
        try:
            run_config = DAQConfigParser.parse(run_config_dir,
                                               run_config_name, strict)
        except DAQConfigException as ex:
            raise CnCServerException("Cannot load %s from %s" %
                                     (run_config_name, run_config_dir), ex)
        logger.info("Loaded run configuration \"%s\"" % run_config_name)

        name_list = []
        for comp in run_config.components:
            name_list.append(comp.fullname)

        if name_list is None or \
          len(name_list) == 0:  # pylint: disable=len-as-condition
            raise CnCServerException("No components found in" +
                                     " run configuration \"%s\"" % run_config)

        comp_list = []
        try:
            wait_list = self.__collect_components(name_list, comp_list, logger,
                                                  timeout)
        except:
            self.__return_components(comp_list, logger)
            raise

        if wait_list is not None:
            self.__return_components(comp_list, logger)
            self.__restart_missing_components(wait_list, run_config, logger,
                                              daq_data_dir)
            raise MissingComponentException(wait_list)

        set_added = False
        try:
            try:
                runset = self.create_runset(run_config, comp_list, logger)
            except:
                runset = None
                raise

            self.__add_runset(runset)
            set_added = True
        finally:
            if not set_added:
                self.__return_components(comp_list, logger)
                runset = None

        if runset is not None:
            (release, revision) = self.release
            try:
                if self.__starting:
                    # figure out how components should be connected
                    conn_map = runset.build_connection_map()
                if self.__starting:
                    # connect components to each other
                    runset.connect(conn_map)
                if self.__starting:
                    # set the order in which components should be configured
                    runset.set_order(conn_map, logger)
                if self.__starting:
                    # configure components
                    runset.configure()
                if self.__starting:
                    # if this is a replay run, compute the offset for hit times
                    if run_config.update_hitspool_times:
                        runset.init_replay_hubs()
                if not self.__starting:
                    # if the process was interrupted at any point,
                    #  throw an exception
                    raise StartInterruptedException("Start interrupted")
            except:
                runset.report_run_start_failure(run_num, release, revision)
                if not force_restart:
                    self.return_runset(runset, logger)
                else:
                    self.restart_runset(runset, logger)
                raise

            cstr = ComponentManager.format_component_list(runset.components)
            logger.info("Built runset #%d: %s" % (runset.id, cstr))

        return runset

    def __remove_runset(self, runset):
        """
        Remove the runset and return all the components to the pool.

        This method can throw ValueError if the runset is not found
        """
        with self.__sets_lock:
            self.__sets.remove(runset)

    def __restart_missing_components(self, wait_list, run_config, logger,
                                     daq_data_dir):
        clu_cfg = self.get_cluster_config(run_config=run_config)
        if clu_cfg is None:
            logger.error("Cannot restart missing components:"
                         " No cluster config")
        else:
            (dead_list, missing_list) = clu_cfg.extract_components(wait_list)
            if len(missing_list) > 0:  # pylint: disable=len-as-condition
                cstr = ComponentManager.format_component_list(missing_list)
                logger.error(("Cannot restart missing %s: Not found in"
                              " cluster config \"%s\"") %
                             (cstr, clu_cfg.config_name))

            if len(dead_list) > 0:  # pylint: disable=len-as-condition
                self.cycle_components(dead_list, run_config.configdir,
                                      daq_data_dir, logger)

    def __return_components(self, comp_list, logger):
        ComponentGroup.run_simple(OpResetComponent, comp_list, (), logger,
                                  report_errors=True)

        with self.__pool_lock:
            for comp in comp_list:
                self.__add_to_pool(comp)

    def add(self, comp):
        "Add the component to the config server's pool"
        with self.__pool_lock:
            return self.__add_to_pool(comp)

    @property
    def components(self):
        comp_list = []
        with self.__pool_lock:
            for k in self.__pool:
                for comp in self.__pool[k]:
                    comp_list.append(comp)

        return comp_list

    def create_runset(self, run_config, comp_list, logger):
        return RunSet(self, run_config, comp_list, logger)

    # pylint: disable=no-self-use
    def cycle_components(self, comp_list, run_config_dir, daq_data_dir, logger,
                         verbose=False, kill_with_9=False, event_check=False):
        RunSet.cycle_components(comp_list, run_config_dir, daq_data_dir,
                                logger, verbose=verbose,
                                kill_with_9=kill_with_9,
                                event_check=event_check)

    def find_runset(self, rsid):
        "Find the runset with the specified ID"
        with self.__sets_lock:
            for runset in self.__sets:
                if runset.id == rsid:
                    runset = runset
                    return runset

        return None

    def get_cluster_config(self, run_config=None):
        raise NotImplementedError("Unimplemented")

    def get_runsets_in_error_state(self):
        problems = []
        for runset in self.__sets:
            if runset.state == RunSetState.ERROR:
                problems.append(runset)
        return problems

    @property
    def is_starting(self):
        return self.__starting

    def make_runset(self, run_config_dir, run_config_name, run_num, timeout,
                    logger, daq_data_dir, force_restart=True, strict=False):
        "Build a runset from the specified run configuration"
        try:
            self.__starting = True
            return self.__make_runset_internal(run_config_dir, run_config_name,
                                               run_num, timeout, logger,
                                               daq_data_dir,
                                               force_restart=force_restart,
                                               strict=strict)
        finally:
            self.__starting = False

    def monitor_clients(self, logger=None):
        "check that all components in the pool are still alive"
        count = 0

        clients = []
        for pool_bin in list(self.__pool.values()):
            for client in pool_bin:
                clients.append(client)

        states = ComponentGroup.run_simple(OpGetState, clients, (), logger)
        for client in clients:
            if client in states:
                state_str = str(states[client])
            else:
                state_str = DAQClientState.MISSING

            if state_str == DAQClientState.DEAD or \
               (state_str == DAQClientState.HANGING and client.is_dead):
                self.remove(client)
                try:
                    client.close()
                except:  # pylint: disable=bare-except
                    if logger is not None:
                        logger.error("Could not close %s: %s" %
                                     (client.fullname, exc_string()))
            elif state_str in (DAQClientState.MISSING, DAQClientState.HANGING):
                client.add_dead_count()
            else:
                count += 1

        return count

    @property
    def num_components(self):
        tot = 0

        with self.__pool_lock:
            for bin_name in self.__pool:
                tot += len(self.__pool[bin_name])

        return tot

    @property
    def num_sets(self):
        return len(self.__sets)

    @property
    def num_unused(self):
        return len(self.__pool)

    @property
    def release(self):
        return (None, None)

    def remove(self, comp):
        "Remove a component from the pool"
        with self.__pool_lock:
            if comp.name in self.__pool:
                self.__pool[comp.name].remove(comp)
                pool_len = len(self.__pool[comp.name])
                if pool_len == 0:
                    del self.__pool[comp.name]

        return comp

    def restart_runset(self, runset, logger, verbose=False, kill_with_9=False,
                       event_check=False):
        try:
            self.__remove_runset(runset)
        except ValueError:
            logger.error("Cannot remove %s (#%d available - %s)" %
                         (runset, len(self.__sets), self.__sets))

        try:
            self.restart_runset_components(runset, verbose=verbose,
                                           kill_with_9=kill_with_9,
                                           event_check=event_check)
        except:  # pylint: disable=bare-except
            logger.error("Cannot restart %s (#%d available - %s): %s" %
                         (runset, len(self.__sets), self.__sets, exc_string()))

        runset.destroy(ignore_components=True)

    def restart_runset_components(self, runset, verbose=False,
                                  kill_with_9=True, event_check=False):
        "Placeholder for subclass method"
        raise CnCServerException("Unimplemented for %s" % type(self))

    def return_all(self, kill_running=True):
        """
        Return all runset components to the pool
        NOTE: This DESTROYS all runsets, unless there is an active run
        """
        removed = None
        with self.__sets_lock:
            for runset in self.__sets:
                if runset.is_running and not kill_running:
                    return False
            removed = self.__sets[:]
            del self.__sets[:]

        saved_exc = None
        for runset in removed:
            try:
                self.return_runset_components(runset)
            except:  # pylint: disable=bare-except
                if not saved_exc:
                    saved_exc = sys.exc_info()

            try:
                runset.destroy()
            except:  # pylint: disable=bare-except
                if not saved_exc:
                    saved_exc = sys.exc_info()

        if saved_exc:
            reraise_excinfo(saved_exc)

        return True

    def return_runset(self, runset, logger):
        "Return runset components to the pool"
        try:
            self.__remove_runset(runset)
        except ValueError:
            logger.error("Cannot remove %s (#%d available - %s)" %
                         (runset, len(self.__sets), self.__sets))

        saved_exc = None
        try:
            self.return_runset_components(runset)
        finally:
            try:
                runset.destroy()
            except:  # pylint: disable=bare-except
                saved_exc = sys.exc_info()

        if saved_exc:
            reraise_excinfo(saved_exc)

    def return_runset_components(self, runset, verbose=False, kill_with_9=True,
                                 event_check=False):
        "Placeholder for subclass method"
        raise CnCServerException("Unimplemented for %s" % type(self))

    def runset(self, num):
        return self.__sets[num]

    @property
    def runset_ids(self):
        "List active runset IDs"
        rsids = []

        with self.__sets_lock:
            for runset in self.__sets:
                rsids.append(runset.id)

        return rsids

    def stop_collecting(self):
        if self.__starting:
            self.__starting = False


class ThreadedRPCServer(ThreadingMixIn, RPCServer):
    "The standard out-of-the-both threaded RPC server"


class Connector(object):
    "Component connector"

    INPUT = "i"
    OUTPUT = "o"
    OPT_INPUT = "I"
    OPT_OUTPUT = "O"

    def __init__(self, name, descr_char, port):
        """
        Connector constructor
        name - connection name
        descr_char - connection description character (I, i, O, o)
        port - IP port number (for input connections)
        """
        self.__name = name
        if isinstance(descr_char, bool):
            raise Exception("Convert to new format")
        self.__descr_char = descr_char
        if self.is_input:
            self.__port = port
        else:
            self.__port = None

    def __str__(self):
        "String description"
        if self.is_optional:
            conn_char = "~"
        else:
            conn_char = "="
        if self.is_input:
            return '%d%s>%s' % (self.__port, conn_char, self.__name)
        return self.__name + conn_char + '>'

    @property
    def is_input(self):
        "Return True if this is an input connector"
        return self.__descr_char == self.INPUT or \
            self.__descr_char == self.OPT_INPUT

    @property
    def is_optional(self):
        "Return True if this is an optional connector"
        return self.__descr_char == self.OPT_INPUT or \
            self.__descr_char == self.OPT_OUTPUT

    @property
    def is_output(self):
        "Return True if this is an output connector"
        return self.__descr_char == self.OUTPUT or \
            self.__descr_char == self.OPT_OUTPUT

    @property
    def name(self):
        "Return the connector name"
        return self.__name

    @property
    def port(self):
        "Return connector port number"
        return self.__port


class CnCServer(DAQPool):
    "Command and Control Server"

    # max time to wait for components to register
    REGISTRATION_TIMEOUT = 60

    def __init__(self, name="GenericServer", cluster_desc=None, copy_dir=None,
                 dash_dir=None, default_log_dir=None, run_config_dir=None,
                 daq_data_dir=None, jade_dir=None, log_host=None,
                 log_port=None, live_host=None, live_port=None,
                 restart_on_error=True, force_restart=True, test_only=False,
                 quiet=False):
        "Create a DAQ command and configuration server"
        self.__name = name
        self.__version_info = get_scmversion()

        self.__id = int(time.time())

        self.__cluster_desc = cluster_desc
        self.__copy_dir = copy_dir
        self.__dash_dir = dash_dir if dash_dir is not None \
          else os.path.join(PDAQ_HOME, "dash")
        self.__run_config_dir = run_config_dir
        self.__daq_data_dir = daq_data_dir
        self.__jade_dir = jade_dir
        self.__default_log_dir = default_log_dir

        self.__cluster_config = None

        self.__restart_on_error = restart_on_error
        self.__force_restart = force_restart
        self.__quiet = quiet

        self.__monitoring = False

        self.__live = None

        self.__open_file_count = None

        super(CnCServer, self).__init__()

        # whine if new signal handler overrides an existing signal handler
        signum = signal.SIGINT
        old_handler = signal.getsignal(signum)
        if old_handler not in (signal.SIG_IGN, signal.SIG_DFL):
            print("Overriding %s handler <%s>%s for CnCServer" %
                  (self.__get_signal_name(signum), type(old_handler),
                   old_handler), file=sys.stderr)

        # close and exit on ctrl-C
        #
        signal.signal(signal.SIGINT, self.__close_on_sigint)

        self.__log = self.create_cnc_logger(quiet=(test_only or quiet))

        self.__log_server = \
            self.open_log_server(DAQPort.CATCHALL, self.__default_log_dir)
        self.__log_server.start_serving()

        if log_host is None or log_port is None:
            log_host = "localhost"
            log_port = DAQPort.CATCHALL

        self.__log.open_log(log_host, log_port, live_host, live_port)

        if test_only:
            self.__server = None
        else:
            while True:
                try:
                    self.__server = ThreadedRPCServer(DAQPort.CNCSERVER)
                    break
                except socket.error as exc:
                    self.__log.error("Couldn't create server socket: %s" % exc)
                    sys.exit("Couldn't create server socket: %s" % exc)

        if self.__server is not None:
            self.__server.register_function(self.rpc_close_files)
            self.__server.register_function(self.rpc_component_connector_info)
            self.__server.register_function(self.rpc_component_count)
            self.__server.register_function(self.rpc_component_get_bean_field)
            self.__server.register_function(self.rpc_component_list)
            self.__server.register_function(self.rpc_component_list_beans)
            self.__server.register_function(
                self.rpc_component_list_bean_fields)
            self.__server.register_function(self.rpc_component_list_dicts)
            self.__server.register_function(self.rpc_component_register)
            self.__server.register_function(self.rpc_cycle_live)
            self.__server.register_function(self.rpc_end_all)
            self.__server.register_function(self.rpc_list_open_files)
            self.__server.register_function(self.rpc_ping)
            self.__server.register_function(self.rpc_register_component)
            self.__server.register_function(self.rpc_run_summary)
            self.__server.register_function(self.rpc_runset_break)
            self.__server.register_function(self.rpc_runset_configname)
            self.__server.register_function(self.rpc_runset_count)
            self.__server.register_function(self.rpc_runset_events)
            self.__server.register_function(self.rpc_runset_list)
            self.__server.register_function(self.rpc_runset_list_ids)
            self.__server.register_function(self.rpc_runset_make)
            self.__server.register_function(self.rpc_runset_monitor_run)
            self.__server.register_function(self.rpc_runset_start_run)
            self.__server.register_function(self.rpc_runset_state)
            self.__server.register_function(self.rpc_runset_stop_run)
            self.__server.register_function(self.rpc_runset_subrun)
            self.__server.register_function(self.rpc_runset_switch_run)
            self.__server.register_function(self.rpc_version)

        DumpThreadsOnSignal(sys.stderr, logger=self.__log)

    def __str__(self):
        return "%s<%s>" % (self.__name, self.get_cluster_config().config_name)

    def __close_on_sigint(self,
                          signum, frame):  # pylint: disable=unused-argument
        print("Shutting down...", file=sys.stderr)

        closed = False
        try:
            if self.close_server(False):
                closed = True
        except:
            print("Error while closing RPC server\n%s" %
                  traceback.format_exc())

        if not closed:
            print("Cannot exit with active runset(s)", file=sys.stderr)
        else:
            print("\nExiting", file=sys.stderr)
            # DumpThreadsOnSignal.dump_threads(file_handle=sys.stderr)
            sys.exit(0)

    @staticmethod
    def __count_file_descriptors():
        "Count number of open file descriptors for this process"
        if not sys.platform.startswith("linux"):
            return 0

        path = "/proc/%d/fd" % os.getpid()
        if not os.path.exists(path):
            raise CnCServerException("Path \"%s\" does not exist" % path)

        count = len(os.listdir(path))

        return count

    def __find_component_by_id(self, comp_id, include_runset_components=False):
        for comp in self.components:
            if comp.id == comp_id:
                return comp

        if include_runset_components:
            for rsid in self.runset_ids:
                runset = self.find_runset(rsid)
                for comp in runset.components:
                    if comp.id == comp_id:
                        return comp

        return None

    def __get_components(self, id_list, get_all):
        comp_list = []

        if id_list is None or \
          len(id_list) == 0:  # pylint: disable=len-as-condition
            comp_list += self.components
        else:
            for comp in self.components:
                for i in [j for j, cid in enumerate(id_list)
                          if cid == comp.id]:
                    comp_list.append(comp)
                    del id_list[i]
                    break

        if get_all or (id_list is not None and
                       len(id_list) > 0):  # pylint: disable=len-as-condition
            for rsid in self.runset_ids:
                runset = self.find_runset(rsid)
                if get_all:
                    comp_list += runset.components
                else:
                    for comp in runset.components:
                        for idx in [j for j, cid in enumerate(id_list)
                                    if cid == comp.id]:
                            comp_list.append(comp)
                            del id_list[idx]
                            break
                    if len(id_list) == 0:  # pylint: disable=len-as-condition
                        break

        return comp_list

    @classmethod
    def __get_signal_name(cls, signum):
        if sys.version_info >= (3, 5):
            return signal.Signals(signum).name

        for signame in dir(signal):
            if signame.startswith('SIG') and '_' not in signame and \
              getattr(signal, signame) == signum:
                return signame

        return "Mystery signal #%d" % (signum, )

    def __list_component_dicts(self, comp_list):
        slst = []

        states = ComponentGroup.run_simple(OpGetState, comp_list, (),
                                           self.__log)
        for comp in comp_list:
            if comp in states:
                state_str = str(states[comp])
            else:
                state_str = DAQClientState.DEAD

            cdict = comp.map()
            cdict["state"] = state_str

            slst.append(cdict)

        return slst

    @classmethod
    def __list_cnc_open_files(cls):
        user_list = ListOpenFiles.run(os.getpid())

        if user_list is None or \
          len(user_list) <= 0:  # pylint: disable=len-as-condition
            raise CnCServerException("No open file list available!")

        if len(user_list) > 1:
            raise CnCServerException(("Expected 1 user from ListOpenFiles," +
                                      " not %d") % len(user_list))

        of_list = []
        for fdata in user_list[0].files():
            if isinstance(fdata.file_desc, str) or fdata.file_desc < 3:
                continue

            of_list.append(fdata)

        return of_list

    def __report_open_files(self):
        try:
            of_list = self.__list_cnc_open_files()
        except:  # pylint: disable=bare-except
            self.__log.error("Cannot list open files: " + exc_string())
            return

        errmsg = "Open File List\n=============="
        for fdata in of_list:
            if fdata.protocol is None:
                extra = ""
            else:
                extra = " (%s)" % fdata.protocol
            errmsg += "\n%4.4s %6.6s %s%s" % \
                      (fdata.file_desc, fdata.file_type, fdata.name, extra)

        self.__log.error(errmsg)

    def break_runset(self, runset):
        had_error = False
        if not runset.is_ready:
            try:
                had_error = runset.stop_run("BreakRunset")
            except:  # pylint: disable=bare-except
                self.__log.error("While breaking %s: %s" %
                                 (runset, exc_string()))

        try:
            if self.__force_restart or (had_error and self.__restart_on_error):
                self.restart_runset(runset, self.__log)
            else:
                self.return_runset(runset, self.__log)
        except:  # pylint: disable=bare-except
            self.__log.error("Failed to break %s: %s" %
                             (runset, exc_string()))

    @property
    def client_statistics(self):
        # pylint: disable=no-value-for-parameter
        return RPCClient.client_statistics()

    def close_server(self, kill_running=True):
        try:
            if not self.return_all(kill_running):
                return False
        except:  # pylint: disable=bare-except
            print("Failed to return one or more runset components"
                  " to the pool\n%s" % traceback.format_exc())

        self.__monitoring = False
        if self.__server is not None:
            try:
                self.__server.server_close()
            except:
                pass

        ComponentGroup.run_simple(OpClose, self.components, (), self.__log,
                                  report_errors=True)

        self.__log.close_final()
        if self.__log_server is not None:
            self.__log_server.stop_serving()
            self.__log_server = None

        try:
            self.__live.close()
        except:
            pass

        return True

    def create_client(self, name, num, host, port, mbean_port, connectors):
        "overrideable method used for testing"
        return DAQClient(name, num, host, port, mbean_port, connectors,
                         self.__quiet)

    def create_cnc_logger(self, quiet):  # pylint: disable=no-self-use
        return CnCLogger("CnC", quiet=quiet)

    def get_cluster_config(self, run_config=None):
        if self.__cluster_config is None:
            cdesc = self.__cluster_desc
            cfg_dir = self.__run_config_dir
            try:
                clucfg = DAQConfigParser.\
                  get_cluster_configuration(None, use_active_config=True,
                                            cluster_desc=cdesc,
                                            config_dir=cfg_dir,
                                            validate=False)
                self.__cluster_config = clucfg
            except XMLBadFileError:
                if cdesc is None:
                    cdesc_str = ""
                else:
                    cdesc_str = " for cluster \"%s\"" % cdesc
                raise CnCServerException("Cannot find cluster configuration" +
                                         " %s: %s" % (cdesc_str, exc_string()))
        else:
            try:
                self.__cluster_config.load_if_changed(run_config)
            except Exception as ex:  # pylint: disable=broad-except
                self.__log.error("Cannot reload cluster config \"%s\": %s" %
                                 (self.__cluster_config.description, ex))

        return self.__cluster_config

    @property
    def release(self):
        return (self.__version_info["release"],
                self.__version_info["repo_rev"])

    def make_runset_from_run_config(self, run_config, run_num,
                                    timeout=REGISTRATION_TIMEOUT,
                                    strict=False):
        return self.make_runset(self.__run_config_dir, run_config, run_num,
                                timeout, self.__log, self.__daq_data_dir,
                                force_restart=self.__force_restart,
                                strict=strict)

    def monitor_loop(self):
        "Monitor components to ensure they're still alive"
        new = True
        check_clients = 0
        last_count = 0
        self.__monitoring = True
        while self.__monitoring:
            # check clients every 5 seconds or so
            #
            if check_clients == 5:
                check_clients = 0
                try:
                    count = self.monitor_clients(self.__log)
                except:  # pylint: disable=bare-except
                    self.__log.error("Monitoring clients: " + exc_string())
                    count = last_count

                new = (last_count != count)
                if new and not self.__quiet:
                    print("%d bins, %d comps" %
                          (self.num_unused, count), file=sys.stderr)

                last_count = count

            check_clients += 1

            problems = self.get_runsets_in_error_state()
            for runset in problems:
                self.__log.error("Returning runset#%d (state=%s)" %
                                 (runset.id, runset.state))
                try:
                    if self.__force_restart:
                        self.restart_runset(runset, self.__log)
                    else:
                        self.return_runset(runset, self.__log)
                except:  # pylint: disable=bare-except
                    self.__log.error("Failed to return %s: %s" %
                                     (runset, exc_string()))

            time.sleep(1)

    @property
    def name(self):
        return self.__name

    def open_log_server(self, port, log_dir):
        log_name = os.path.join(log_dir, "catchall.log")
        return LogSocketServer(port, "CnCServer", log_name, quiet=self.__quiet)

    def restart_runset_components(self, runset, verbose=False,
                                  kill_with_9=True, event_check=False):
        clu_cfg = self.get_cluster_config(run_config=runset.run_config_data)
        runset.restart_all_components(clu_cfg, self.__run_config_dir,
                                      self.__daq_data_dir, verbose=verbose,
                                      kill_with_9=kill_with_9,
                                      event_check=event_check)

    def return_runset_components(self, runset, verbose=False, kill_with_9=True,
                                 event_check=False):
        clu_cfg = self.get_cluster_config(run_config=runset.run_config_data)
        runset.return_components(self, clu_cfg, self.__run_config_dir,
                                 self.__daq_data_dir, verbose=verbose,
                                 kill_with_9=kill_with_9,
                                 event_check=event_check)

    def rpc_close_files(self, fd_list):
        saved_exc = None
        for file_handle in fd_list:
            try:
                os.close(file_handle)
                self.__log.error("Manually closed file #%s" % file_handle)
            except OSError:
                if not saved_exc:
                    saved_exc = (file_handle, exc_string())

        if saved_exc:
            raise CnCServerException("Cannot close file #%s: %s" %
                                     (saved_exc[0], saved_exc[1]))

        return 1

    def rpc_component_connector_info(self, id_list=None, get_all=True):
        "list component connector information"
        comp_list = self.__get_components(id_list, get_all)

        results = ComponentGroup.run_simple(OpGetConnectionInfo, comp_list, (),
                                            self.__log)

        slst = []
        for comp in comp_list:
            if comp in results:
                result = results[comp]
            else:
                result = DAQClientState.DEAD

            cdict = comp.map()

            if not isinstance(result, list):
                cdict["error"] = str(result)
            else:
                cdict["conn"] = result

            slst.append(cdict)

        return slst

    def rpc_component_count(self):
        "return number of components currently registered"
        return self.num_components

    def rpc_component_get_bean_field(self, comp_id, bean, field,
                                     include_runset_components=False):
        comp = self.__find_component_by_id(comp_id, include_runset_components)
        if comp is None:
            raise CnCServerException("Unknown component #%d" % comp_id)

        return comp.mbean.get(bean, field)

    def rpc_component_list(self, include_runset_components=False):
        "return dictionary of component names -> IDs"
        id_dict = {}
        for comp in self.components:
            id_dict[comp.fullname] = comp.id

        if include_runset_components:
            for rsid in self.runset_ids:
                runset = self.find_runset(rsid)
                for comp in runset.components:
                    id_dict[comp.fullname] = comp.id

        return id_dict

    def rpc_component_list_beans(self, comp_id,
                                 include_runset_components=False):
        comp = self.__find_component_by_id(comp_id, include_runset_components)
        if comp is not None:
            return comp.mbean.get_bean_names()

        raise CnCServerException("Unknown component #%d" % comp_id)

    def rpc_component_list_bean_fields(self, comp_id, bean,
                                       include_runset_components=False):
        comp = self.__find_component_by_id(comp_id, include_runset_components)
        if comp is not None:
            return comp.mbean.get_bean_fields(bean)

        raise CnCServerException("Unknown component #%d" % comp_id)

    def rpc_component_list_dicts(self, id_list=None, get_all=True):
        "list specific components"
        return self.__list_component_dicts(self.__get_components(id_list,
                                                                 get_all))

    def rpc_component_register(self, name, num, host, port, mbean_port,
                               conn_array):
        "register a component with the server"

        if not isinstance(name, str) or name == "":
            raise CnCServerException("Bad component name (should be a string)")
        if not isinstance(num, int):
            raise CnCServerException("Bad component number" +
                                     " (should be an integer)")

        connectors = []
        for idx, conn in enumerate(conn_array):
            if not isinstance(conn, tuple) and not isinstance(conn, list):
                errmsg = "Bad %s#%d connector#%d \"%s\"%s" % \
                    (name, num, idx, str(conn), str(type(conn)))
                self.__log.info(errmsg)
                raise CnCServerException(errmsg)
            if len(conn) != 3:
                errmsg = ("Bad %s#%d connector#%d %s (should have 3" +
                          " elements)") % (name, num, idx, str(conn))
                self.__log.info(errmsg)
                raise CnCServerException(errmsg)
            if not isinstance(conn[0], str) or conn[0] == "":
                errmsg = ("Bad %s#%d connector#%d %s (first element should" +
                          " be name)") % (name, num, idx, str(conn))
                self.__log.info(errmsg)
                raise CnCServerException(errmsg)
            if not isinstance(conn[1], str) or len(conn[1]) != 1:
                errmsg = ("Bad %s#%d connector#%d %s (second element should" +
                          " be descr_char)") % (name, num, idx, str(conn))
                self.__log.info(errmsg)
                raise CnCServerException(errmsg)

            if isinstance(conn[2], int):
                conn_port = conn[2]
            elif isinstance(conn[2], str):
                conn_port = int(conn[2])
            else:
                errmsg = ("Bad %s#%d connector#%d %s (third element should" +
                          " be int)") % (name, num, idx, str(conn))
                self.__log.info(errmsg)
                raise CnCServerException(errmsg)
            connectors.append(Connector(conn[0], conn[1], conn_port))

        client = self.create_client(name, num, host, port, mbean_port,
                                    connectors)

        if self.add(client):
            self.__log.debug("Registered %s" % client.fullname)
        else:
            self.__log.debug("Ignoring previously registered %s" %
                             client.fullname)

        log_host = ip.convert_localhost_to_address(self.__log.log_host)

        log_port = self.__log.log_port
        if log_port is None:
            if self.__log_server is not None:
                log_port = self.__log_server.port
            else:
                log_host = ""
                log_port = 0

        live_host = ip.convert_localhost_to_address(self.__log.live_host)

        live_port = self.__log.live_port
        if live_port is None:
            live_host = ""
            live_port = 0

        return {"id": client.id,
                "logIP": log_host,
                "logPort": log_port,
                "liveIP": live_host,
                "livePort": live_port,
                "serverId": self.__id}

    def rpc_cycle_live(self):
        "Restart DAQLive thread"
        self.__live.close()
        self.__live = self.start_live_thread()

        return "OK"

    def rpc_end_all(self):
        "reset all clients"
        ComponentGroup.run_simple(OpResetComponent, self.components, (),
                                  self.__log, report_errors=True)
        return 1

    def rpc_list_open_files(self):
        "list open files"
        of_list = self.__list_cnc_open_files()

        of_vals = []
        for fdata in of_list:
            if fdata.protocol is None:
                extra = ""
            else:
                extra = " (%s)" % fdata.protocol
            of_vals.append((fdata.file_desc, fdata.file_type, fdata.name,
                            extra))

        return of_vals

    def rpc_ping(self):
        "remote method for far end to confirm that server is still alive"
        return self.__id

    def rpc_register_component(self, name, num, host, port, mbean_port,
                               conn_array):
        "backward compatibility shim"
        return self.rpc_component_register(name, num, host, port, mbean_port,
                                           conn_array)

    def rpc_run_summary(self, run_num):
        "Return run summary information (if available)"
        return RunSet.get_run_summary(self.__default_log_dir, run_num)

    def rpc_runset_break(self, rsid):
        "break up the specified runset"
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        if runset.is_running:
            raise CnCServerException("Cannot break up running runset #%d" %
                                     rsid)

        self.break_runset(runset)

        return "OK"

    def rpc_runset_configname(self, rsid):
        "return run configuration name for this runset"
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        clucfg = runset.cluster_config
        if clucfg is None:
            return runset.config_name
        return "%s@%s" % (runset.config_name, clucfg)

    def rpc_runset_count(self):
        "return number of existing run sets"
        return self.num_sets

    def rpc_runset_events(self, rsid, subrun_number):
        """
        get the number of events for the specified subrun
        from the specified runset
        """
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        return runset.subrun_events(subrun_number)

    def rpc_runset_list_ids(self):
        """return a list of active runset IDs"""
        return self.runset_ids

    def rpc_runset_list(self, rsid):
        """
        return a list of information about all components
        in the specified runset
        """
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        return self.__list_component_dicts(runset.components)

    def rpc_runset_make(self, run_config, run_num=None, strict=False):
        "build a runset from the specified run configuration"
        if self.__run_config_dir is None:
            raise CnCServerException("Run configuration directory" +
                                     " has not been set")
        if isinstance(run_config, list):
            raise CnCServerException("Must now specify a run config name," +
                                     " not a list of components")

        try:
            runset = self.make_runset_from_run_config(run_config, run_num,
                                                      strict=strict)
        except MissingComponentException as mce:
            self.__log.error("%s while making runset from \"%s\"" %
                             (str(mce), run_config))
            runset = None
        except:  # pylint: disable=bare-except
            self.__log.error("While making runset from \"%s\": %s" %
                             (run_config, exc_string()))
            runset = None

        if runset is None:
            return -1

        return runset.id

    def rpc_runset_monitor_run(self, rsid, run_num):
        "Return monitoring data for the runset"
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        monidict = runset.get_event_counts(run_num)
        for key, val in list(monidict.items()):
            if not isinstance(val, str) and \
              not isinstance(val, numbers.Number) and \
              (sys.version_info >= (3, 0) or not isinstance(val, unicode)):
                monidict[key] = str(val)

        return monidict

    def rpc_runset_start_run(self, rsid, run_num, run_options, log_dir=None):
        """
        start a run with the specified runset

        rsid - runset ID
        run_num - run number
        run_options - bitmapped word (described in RunOption.py)
        log_dir - directory where log files are written, defaults to the
                 value specified at CnCServer startup time
        """
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        if log_dir is None:
            log_dir = self.__default_log_dir

        if not self.start_run(runset, run_num, run_options, log_dir=log_dir):
            return "FAILED"

        return "OK"

    def rpc_runset_state(self, rsid):
        "get the state of the specified runset"
        runset = self.find_runset(rsid)

        if not runset:
            return RunSetState.UNKNOWN

        return runset.state

    def rpc_runset_stop_run(self, rsid):
        "stop a run with the specified runset"
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        delayed_exc = None
        try:
            had_error = runset.stop_run(RunSet.NORMAL_STOP)
        except ValueError:
            had_error = True
            delayed_exc = sys.exc_info()

        chk = 50
        while runset.stopping() and chk > 0:
            chk -= 1
            time.sleep(1)

        if runset.stopping():
            raise CnCServerException("Runset#%d is still stopping" % rsid)

        if self.__force_restart or (had_error and self.__restart_on_error):
            self.restart_runset(runset, self.__log)

        if delayed_exc:
            reraise_excinfo(delayed_exc)

        return "OK"

    def rpc_runset_subrun(self, rsid, subrun_id, subrun_data):
        "start a subrun with the specified runset"
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        runset.subrun(subrun_id, subrun_data)

        return "OK"

    def rpc_runset_switch_run(self, rsid, run_num):
        "switch the specified runset to a new run number"
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        runset.switch_run(run_num)

        return "OK"

    def rpc_version(self):
        "return the CnCServer release/revision info"
        return self.__version_info

    def run(self):
        "Start a server"
        self.__log.info("Version info: " +
                        get_scmversion_str(info=self.__version_info))

        thrd = threading.Thread(name="CnCServer", target=self.monitor_loop)
        thrd.setDaemon(True)
        thrd.start()

        try:
            self.__live = self.start_live_thread()
        except:  # pylint: disable=bare-except
            self.__log.error("Cannot start I3Live thread: " + exc_string())

        self.__server.serve_forever()
        # DumpThreadsOnSignal.dump_threads(file_handle=sys.stderr)

    def save_catchall(self, run_dir):
        "save the catchall.log file to the run directory"
        catchall_file = os.path.join(self.__default_log_dir, "catchall.log")
        if not os.path.exists(catchall_file):
            return

        if self.__log_server is not None:
            self.__log_server.stop_serving()

        os.rename(catchall_file, os.path.join(run_dir, "catchall.log"))

        if self.__log_server is not None:
            self.__log_server.start_serving()

    @property
    def server_statistics(self):
        return self.__server.server_statistics()

    def start_live_thread(self):
        "Start I3Live interface thread"
        live = DAQLive(self, self.__log)

        thrd = threading.Thread(name="DAQLive", target=live.run)
        thrd.setDaemon(True)
        thrd.start()

        return live

    def start_run(self, runset, run_num, run_options, log_dir=None):
        if log_dir is None:
            log_dir = self.__default_log_dir

        try:
            open_count = self.__count_file_descriptors()
        except:  # pylint: disable=bare-except
            self.__log.error("Cannot count open files: %s" % exc_string())
            open_count = 0

        clu_cfg = self.get_cluster_config(run_config=runset.run_config_data)
        success = False

        failed_trace = None
        try:
            runset.start_run(run_num, clu_cfg, run_options,
                             self.__version_info, self.__jade_dir,
                             copy_dir=self.__copy_dir, log_dir=log_dir,
                             quiet=self.__quiet)
            success = True
        except:  # pylint: disable=bare-except
            failed_trace = traceback.format_exc()

        # file leaks are reported after start_run() because dash.log
        # is created in that method
        #
        if self.__open_file_count is None:
            self.__open_file_count = open_count
        elif open_count > self.__open_file_count:
            runset.log_to_dash("WARNING: Possible file leak; open file count"
                               " increased from %d to %d" %
                               (self.__open_file_count, open_count))
            if open_count - self.__open_file_count > 40:
                self.__report_open_files()
            self.__open_file_count = open_count

        if not success:
            rsid = runset.id
            try:
                self.__log.error("Cannot start runset#%s: %s" %
                                 (rsid, failed_trace))
                runset.reset()
                runset.destroy()
            except:  # pylint: disable=bare-except
                self.__log.error("Cannot reset runset#%s: %s" %
                                 (rsid, failed_trace))
            raise CnCServerException("Cannot start runset %s" % (runset, ))

        return success

    def update_rates(self, rsid):
        """
        This is a convenience method to allow unit tests to force rate updates
        """
        runset = self.find_runset(rsid)

        if not runset:
            raise CnCServerException('Could not find runset#%d' % rsid)

        return runset.update_rates()

    def version_info(self):
        return self.__version_info


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--copy-dir", dest="copy_dir",
                        help="Directory for copies of files sent to JADE")
    parser.add_argument("-C", "--cluster-desc", dest="cluster_desc",
                        help="Cluster description name")
    parser.add_argument("-c", "--config-dir", dest="config_dir",
                        help="Directory where run configurations are stored")
    parser.add_argument("-d", "--daemon", dest="daemon",
                        action="store_true", default=False,
                        help="Run as a daemon process")
    parser.add_argument("-D", "--dash-dir", dest="dash_dir",
                        default=os.path.join(PDAQ_HOME, "dash"),
                        help="Directory holding Python scripts")
    parser.add_argument("-f", "--force-restart", dest="force_restart",
                        action="store_true", default=True,
                        help="Force components to restart after every run")
    parser.add_argument("-F", "--no-force-restart", dest="force_restart",
                        action="store_false", default=True,
                        help=("Don't force components to restart"
                              " after every run"))
    parser.add_argument("-k", "--kill", dest="kill",
                        action="store_true", default=False,
                        help="Kill running CnCServer instance(s)")
    parser.add_argument("-l", "--log", dest="log",
                        help="Hostname:port for log server")
    parser.add_argument("-L", "--liveLog", dest="liveLog",
                        help="Hostname:port for IceCube Live")
    parser.add_argument("-o", "--default-log-dir",
                        dest="default_log_dir",
                        default="/mnt/data/pdaq/log",
                        help="Default directory for pDAQ log/monitoring files")
    parser.add_argument("-q", "--data-dir", dest="daq_data_dir",
                        default="/mnt/data/pdaqlocal",
                        help="Directory holding physics/tcal/moni/sn files")
    parser.add_argument("-r", "--restart-on-error", dest="restart_on_error",
                        action="store_true", default=True,
                        help="Restart components if the run ends in an error")
    parser.add_argument("-R", "--no-restart-on-error", dest="restart_on_error",
                        action="store_false", default=True,
                        help=("Don't restart components if the run ends"
                              " in an error"))
    parser.add_argument("-s", "--jade-dir", dest="jade_dir",
                        help=("Directory where JADE will pick up"
                              " logs/moni files"))
    parser.add_argument("-v", "--verbose", dest="quiet",
                        action="store_false", default=True,
                        help="Write catchall messages to console")
    args = parser.parse_args()

    pids = list(find_python_process(os.path.basename(sys.argv[0])))

    if args.kill:
        mypid = os.getpid()
        for pid in pids:
            if pid != mypid:
                os.kill(pid, signal.SIGKILL)

        sys.exit(0)

    if len(pids) > 1:
        sys.exit("ERROR: More than one instance of CnCServer.py" +
                 " is already running!")

    args.daq_data_dir = os.path.abspath(args.daq_data_dir)
    if not os.path.exists(args.daq_data_dir):
        sys.exit(("DAQ data directory '%s' doesn't exist!" +
                  "  Use the -q option, or -h for help.") % args.daq_data_dir)

    if args.jade_dir is not None:
        args.jade_dir = os.path.abspath(args.jade_dir)
        if not os.path.exists(args.jade_dir):
            sys.exit(("JADE directory '%s' doesn't exist!" +
                      "  Use the -s option, or -h for help.") % args.jade_dir)

    if args.copy_dir is not None:
        args.copy_dir = os.path.abspath(args.copy_dir)
        if not os.path.exists(args.copy_dir):
            sys.exit("Log copies directory '%s' doesn't exist!" %
                     args.copy_dir)

    if args.default_log_dir is not None:
        args.default_log_dir = os.path.abspath(args.default_log_dir)
        if not os.path.exists(args.default_log_dir):
            sys.exit("Default log directory '%s' doesn't exist!" %
                     args.default_log_dir)

    if args.log is None:
        log_host = None
        log_port = None
    else:
        colon = args.log.find(':')
        if colon < 0:
            sys.exit("ERROR: Bad log argument '%s'" % args.log)

        log_host = args.log[:colon]
        log_port = int(args.log[colon + 1:])

    if args.liveLog is None:
        live_host = None
        live_port = None
    else:
        colon = args.liveLog.find(':')
        if colon < 0:
            sys.exit("ERROR: Bad liveLog argument '%s'" % args.liveLog)

        live_host = args.liveLog[:colon]
        live_port = int(args.liveLog[colon + 1:])

    if args.daemon:
        Daemon().daemonize()

    if args.config_dir is not None:
        config_dir = args.config_dir
    else:
        config_dir = find_pdaq_config()
    cnc = CnCServer(cluster_desc=args.cluster_desc, name="CnCServer",
                    copy_dir=args.copy_dir, dash_dir=args.dash_dir,
                    run_config_dir=config_dir, daq_data_dir=args.daq_data_dir,
                    jade_dir=args.jade_dir,
                    default_log_dir=args.default_log_dir,
                    log_host=log_host, log_port=log_port, live_host=live_host,
                    live_port=live_port, force_restart=args.force_restart,
                    test_only=False, quiet=args.quiet)
    try:
        cnc.run()
    except KeyboardInterrupt:
        sys.exit("Interrupted.")


if __name__ == "__main__":
    main()
