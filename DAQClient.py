#!/usr/bin/env python
"DAQClient manages a connection to a pDAQ component"

import socket
import threading
try:
    import xmlrpclib as xclient
except ImportError:
    import xmlrpc.client as xclient

from CnCLogger import CnCLogger
from DAQRPC import RPCClient
from UniqueID import UniqueID
from scmversion import get_scmversion_str

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


def unfix_value(obj):
    """
    Look for numbers masquerading as strings.  If an obj is a string and
    successfully converts to a number, return that number.  If obj is a dict
    or list, recurse into it converting all numeric back into numbers.  All
    other types are unaltered.  This pairs with the similarly named fix*
    methods in icecube.daq.juggler.mbean.XMLRPCServer
    """
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            obj[key] = unfix_value(obj[key])
    elif isinstance(obj, list):
        for idx, entry in enumerate(obj):
            obj[idx] = unfix_value(entry)
    elif isinstance(obj, tuple):
        new_obj = []
        for val in obj:
            new_obj.append(unfix_value(val))
        obj = tuple(new_obj)
    elif isinstance(obj, str):
        try:
            if obj.endswith("L"):
                return int(obj[:-1])
            return int(obj)
        except ValueError:
            pass
    return obj


class BeanException(Exception):
    "Base MBean exception"
    pass


class BeanFieldNotFoundException(BeanException):
    "Exception thrown when an MBean field was not found"
    pass


class BeanLoadException(BeanException):
    "Exception thrown when MBean data cannot be loaded from the MBean client"
    pass


class BeanTimeoutException(BeanException):
    "Exception thrown when the MBean client times out"
    pass


class MBeanClient(object):
    "MBean client interface"

    def __init__(self, comp_name, host, port):
        "Python interface to Java MBeanAgent"
        self.__comp_name = comp_name
        self.__client = self.create_client(host, port)
        self.__bean_list = []
        self.__bean_fields = {}

        self.__bean_lock = threading.Lock()
        self.__loaded_info = False

    def __str__(self):
        return "MBeanClient(%s)" % (self.__comp_name, )

    def __load_bean_info(self):
        """
        Get the bean names and fields from the remote client
        Note that self.__bean_lock is acquired before calling this method
        """

        self.__loaded_info = False
        try:
            self.__bean_list = self.__client.mbean.listMBeans()
        except socket.error as serr:
            raise BeanTimeoutException("Cannot get list of %s MBeans"
                                       " <socket error %s>" %
                                       (self.__comp_name, serr))
        except (xclient.Fault, xclient.ProtocolError) as xerr:
            raise BeanTimeoutException("Cannot get list of %s MBeans: %s" %
                                       (self.__comp_name, xerr))
        except:
            raise BeanLoadException("Cannot load list of %s MBeans: %s " %
                                    (self.__comp_name, exc_string()))

        failed = []
        for bean in self.__bean_list:
            try:
                self.__bean_fields[bean] = self.__client.mbean.listGetters(bean)
            except:
                # don't let a single failure abort remaining fetches,
                failed.append(bean)

                # make sure bean has an entry
                if bean not in self.__bean_fields:
                    self.__bean_fields[bean] = []

        if len(failed) > 0:
            raise BeanLoadException("Cannot load %s MBeans %s: %s" %
                                    (self.__comp_name, failed, exc_string()))

        self.__loaded_info = True

    def __lock_and_load(self):
        "load bean info from the remote client if it hasn't yet been loaded"

        if not self.__loaded_info:
            with self.__bean_lock:
                if not self.__loaded_info:
                    self.__load_bean_info()

    def create_client(self, host, port):
        "create an MBean RPC client"
        return RPCClient(host, port)

    def get(self, bean, fld):
        "get the value for a single MBean field"
        try:
            with self.__bean_lock:
                val = self.__client.mbean.get(bean, fld)
        except socket.error as serr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s:%s\":"
                                       " <socket error %s>" %
                                       (self.__comp_name, bean, fld, serr))
        except (xclient.Fault, xclient.ProtocolError) as xerr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s:%s\": %s" %
                                       (self.__comp_name, bean, fld, xerr))
        except:
            raise BeanLoadException("Cannot load %s MBean \"%s:%s\": %s" %
                                    (self.__comp_name, bean, fld,
                                     exc_string()))

        return unfix_value(val)

    def get_attributes(self, bean, fld_list):
        "get the values for a list of MBean fields"
        try:
            with self.__bean_lock:
                attrs = self.__client.mbean.getAttributes(bean, fld_list)
        except socket.error as serr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s\""
                                       " attributes <socket error %s>" %
                                       (self.__comp_name, bean, serr))
        except (xclient.Fault, xclient.ProtocolError) as xerr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s\":"
                                       " attributes %s" %
                                       (self.__comp_name, bean, xerr))
        except:
            raise BeanLoadException("Cannot load %s MBean \"%s\""
                                    " attributes %s: %s" %
                                    (self.__comp_name, bean, fld_list,
                                     exc_string()))

        if not isinstance(attrs, dict):
            raise BeanException("%s getAttributes(%s, %s) should return dict,"
                                " not %s (%s)" % (self.__comp_name, bean,
                                                  fld_list, type(attrs), attrs))

        if len(attrs) > 0:
            for k in list(attrs.keys()):
                attrs[k] = unfix_value(attrs[k])
        return attrs

    def get_bean_names(self):
        "return a list of MBean names associated with this component"
        self.__lock_and_load()

        return self.__bean_list

    def get_bean_fields(self, bean):
        "return a list of fields associated with this component's MBean"
        self.__lock_and_load()

        if bean not in self.__bean_fields:
            msg = "Bean %s not in list of beans for %s" % \
                (bean, self.__comp_name)
            raise BeanFieldNotFoundException(msg)

        return self.__bean_fields[bean]

    def get_dictionary(self):
        "get the value for all MBean fields"
        with self.__bean_lock:
            try:
                attrs = self.__client.mbean.getDictionary()
            except socket.error as serr:
                raise BeanTimeoutException("Cannot get %s MBean attributes:"
                                           " <socket error %s>" %
                                           (self.__comp_name, serr))
            except (xclient.Fault, xclient.ProtocolError) as xerr:
                raise BeanTimeoutException("Cannot get %s MBean attributes:"
                                           " %s" % (self.__comp_name, xerr))
            except:
                raise BeanLoadException("Cannot load %s MBean attributes:"
                                        " %s" %
                                        (self.__comp_name, exc_string()))

        if not isinstance(attrs, dict):
            raise BeanException("%s get_dictionary() should return dict,"
                                " not %s (%s)" % \
                                (self.__comp_name, type(attrs).__name__, attrs))

        if len(attrs) > 0:
            for k in list(attrs.keys()):
                attrs[k] = unfix_value(attrs[k])
        return attrs

    def reload(self):
        "reload MBean names and fields during the next request"
        self.__loaded_info = False


class ComponentName(object):
    "DAQ component name"

    def __init__(self, name, num):
        "Create a component name object"
        self.__name = name
        self.__num = num

    def __repr__(self):
        "Return the full name of this component"
        return self.fullname

    @property
    def filename(self):
        "Return the base name to use for this component's log file"
        return '%s-%d' % (self.__name, self.__num)

    @property
    def fullname(self):
        """
        Return the full name of this component
        (including instance number only on hub components)
        """
        if self.__num == 0 and self.__name[-3:].lower() != 'hub':
            return self.__name
        return '%s#%d' % (self.__name, self.__num)

    @property
    def is_builder(self):
        "Is this an eventBuilder (or debugging fooBuilder)?"
        return self.__name.lower().find("builder") >= 0

    def is_component(self, name, num=-1):
        "Does this component have the specified name and number?"
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def is_hub(self):
        "Return True if this is a hub"
        return self.__name.endswith("Hub")

    @property
    def is_replay_hub(self):
        """
        Return True if this component is simulating a hub by replaying
        previously captured data
        """
        return self.is_hub and self.__name.lower().find("replay") >= 0

    @property
    def name(self):
        "Component name"
        return self.__name

    @property
    def num(self):
        "Component instance number"
        return self.__num


class DAQClientException(Exception):
    "Base DAQ client exception"
    pass


class DAQClientState(object):
    "Valid states for a DAQ client"

    # internal state indicating that the client hasn't answered
    # some number of pings but has not been declared dead
    #
    MISSING = 'missing'

    # internal state indicating that the client is
    # no longer responding to pings
    #
    DEAD = "DEAD"

    # internal state indicating that the client has not answered
    # an XML-RPC call
    #
    HANGING = "hanging"

    # internal state indicating that the most recent XML-RPC call failed
    #
    ERROR = "ERROR"


class DAQClient(ComponentName):
    """DAQ component
    id - internal client ID
    name - component name
    num - component instance number
    host - component host name
    port - component port number
    mbean_port - component's MBean server port number
    connectors - list of Connectors
    client - XML-RPC client
    dead_count - number of sequential failed pings
    cmd_order - order in which start/stop commands are issued
    """

    # maximum number of failed pings before a component is declared dead
    #
    MAX_DEAD_COUNT = 3

    # next component ID
    #
    ID = UniqueID()

    def __init__(self, name, num, host, port, mbean_port, connectors,
                 quiet=False):
        """
        DAQClient constructor
        name - component name
        num - component instance number
        host - component host name
        port - component port number
        mbean_port - component MBean port number
        connectors - list of Connectors
        """

        super(DAQClient, self).__init__(name, num)

        self.__id = next(DAQClient.ID)

        self.__host = host
        self.__port = port
        self.__mbean_port = mbean_port
        self.__connectors = connectors

        self.__dead_count = 0
        self.__cmd_order = None

        self.__log = self.create_logger(quiet=quiet)

        self.__client = self.create_client(host, port)

        try:
            self.__mbean_client = self.create_mbean_client()
        except:
            self.__mbean_client = None

    def __str__(self):
        "String description"
        if self.__port <= 0:
            hp_str = ''
        else:
            hp_str = ' at %s:%d' % (self.__host, self.__port)

        if self.__mbean_port <= 0:
            mbean_str = ''
        else:
            mbean_str = ' M#%d' % self.__mbean_port

        extra_str = ''
        if self.__connectors and len(self.__connectors) > 0:
            first = True
            for conn in self.__connectors:
                if first:
                    extra_str += ' [' + str(conn)
                    first = False
                else:
                    extra_str += ' ' + str(conn)
            extra_str += ']'

        if self.__dead_count == 0:
            dead_str = ''
        else:
            dead_str = " DEAD#%d" % self.__dead_count

        return "ID#%d %s%s%s%s%s" % \
            (self.__id, self.fullname, hp_str, mbean_str, extra_str, dead_str)

    def add_dead_count(self):
        "Increment the 'dead' count"
        self.__dead_count += 1

    def close(self):
        "Close the logger"
        self.__log.close()

    def commit_subrun(self, subrun_num, latest_time):
        "Start marking events with the subrun number"
        try:
            return self.__client.xmlrpc.commitSubrun(subrun_num, latest_time)
        except:
            self.__log.error(exc_string())
            return None

    def configure(self, config_name=None):
        "Configure this component"
        try:
            if config_name is None:
                return self.__client.xmlrpc.configure()
            return self.__client.xmlrpc.configure(config_name)
        except:
            self.__log.error(exc_string())
            return None

    def connect(self, conn_list=None):
        "Connect this component with other components in a runset"

        if not conn_list:
            return self.__client.xmlrpc.connect()

        new_list = []
        for conn in conn_list:
            new_list.append(conn.map())

        return self.__client.xmlrpc.connect(new_list)

    def connectors(self):
        "Return the list of this component's connector descriptions"
        return self.__connectors[:]

    @classmethod
    def create_client(cls, host, port):
        "Create an RPC client for this component"
        return RPCClient(host, port)

    def create_logger(self, quiet):
        "Create a logger for this component"
        return CnCLogger(self.fullname, quiet=quiet)

    def create_mbean_client(self):
        "Create an MBean client for this component"
        return MBeanClient(self.fullname, self.__host, self.__mbean_port)

    def forced_stop(self):
        "Force component to stop running"
        try:
            return self.__client.xmlrpc.forcedStop()
        except:
            self.__log.error(exc_string())
            return None

    def get_replay_start_time(self):
        "Get the earliest time for a replay hub"
        try:
            return unfix_value(self.__client.xmlrpc.getReplayStartTime())
        except:
            self.__log.error(exc_string())
            return None

    def get_run_data(self, run_num):
        "Get the run data for the specified run"
        try:
            return unfix_value(self.__client.xmlrpc.getRunData(run_num))
        except:
            self.__log.error(exc_string())
            return None

    def get_run_number(self):
        "Get the current run number"
        try:
            return self.__client.xmlrpc.getRunNumber()
        except:
            self.__log.error(exc_string())
            return None

    @property
    def host(self):
        "Return the name of the machine hosting this component"
        return self.__host

    @property
    def id(self):
        "Return the CnCServer ID of this component"
        return self.__id

    @property
    def is_dead(self):
        """
        Return True if this component has been declared dead more than
        the maximum number of times
        """
        return self.__dead_count >= self.MAX_DEAD_COUNT

    @property
    def is_dying(self):
        "Return True if this component has been declared dead at least once"
        return self.__dead_count > 0

    @property
    def is_source(self):
        "Is this component a source of data?"

        # XXX Hack for stringHubs which are sources but which confuse
        #     things by also reading requests from the eventBuilder
        if self.is_hub:
            return True

        for conn in self.__connectors:
            if conn.isInput:
                return False

        return True

    def list_connector_states(self):
        "List of state of all this component's input/output handlers"
        return self.__client.xmlrpc.listConnectorStates()

    def log_to(self, log_host, log_port, live_host, live_port):
        "Send log messages to the specified host and port"
        self.__log.open_log(log_host, log_port, live_host, live_port)

        if log_host is None:
            log_host = ''
        if log_port is None:
            log_port = 0
        if live_host is None:
            live_host = ''
        if live_port is None:
            live_port = 0

        self.__client.xmlrpc.logTo(log_host, log_port, live_host, live_port)

        self.__log.debug("Version info: " + get_scmversion_str())

    def map(self):
        "Return a dictionary description of this component"
        return {"id": self.__id,
                "compName": self.name,
                "compNum": self.num,
                "host": self.__host,
                "rpcPort": self.__port,
                "mbeanPort": self.__mbean_port}

    def matches(self, other):
        "Return True if this component matches another component"
        return self.name == other.name and self.num == other.num and \
            self.__host == other.host and self.__port == other.port and \
            self.__mbean_port == other.mbean_port

    @property
    def mbean(self):
        "Return this component's MBean client"
        return self.__mbean_client

    @property
    def mbean_port(self):
        "Return the port number used by this component's MBean server"
        return self.__mbean_port

    @property
    def order(self):
        "Return the order for this component"
        return self.__cmd_order

    @property
    def port(self):
        "Return the port number used by this component's XML-RPC server"
        return self.__port

    def prepare_subrun(self, subrun_num):
        "Start marking events as bogus in preparation for subrun"
        try:
            return self.__client.xmlrpc.prepareSubrun(subrun_num)
        except:
            self.__log.error(exc_string())
            return None

    def reset(self):
        "Reset component back to the idle state"
        self.__log.close_log()
        return self.__client.xmlrpc.reset()

    def reset_logging(self):
        "Reset component back to the idle state"
        self.__log.reset_log()
        return self.__client.xmlrpc.resetLogging()

    def set_first_good_time(self, pay_time):
        "Set the first time where all hubs have reported a hit"
        try:
            self.__client.xmlrpc.setFirstGoodTime(str(pay_time) + "L")
        except:
            self.__log.error(exc_string())

    def set_last_good_time(self, pay_time):
        "Set the last time where all hubs have reported a hit"
        try:
            self.__client.xmlrpc.setLastGoodTime(str(pay_time) + "L")
        except:
            self.__log.error(exc_string())

    def set_order(self, order_num):
        "Set the order in which components are started/stopped"
        self.__cmd_order = order_num

    def set_replay_offset(self, offset):
        "Get the time offset for a replay hub"
        try:
            self.__client.xmlrpc.setReplayOffset(str(offset) + "L")
        except:
            self.__log.error(exc_string())

    def start_run(self, run_num):
        "Start component processing DAQ data"
        try:
            return self.__client.xmlrpc.startRun(run_num)
        except:
            self.__log.error(exc_string())
            return None

    def start_subrun(self, data):
        "Send subrun data to stringHubs"
        try:
            return self.__client.xmlrpc.startSubrun(data)
        except:
            self.__log.error(exc_string())
            return None

    @property
    def state(self):
        "Get current state"
        try:
            state = self.__client.xmlrpc.getState()
        except (socket.error, xclient.Fault, xclient.ProtocolError):
            state = None
        except:
            self.__log.error(exc_string())
            state = None

        if state is not None:
            self.__dead_count = 0
        elif not self.is_dead:
            state = DAQClientState.MISSING
        else:
            state = DAQClientState.DEAD

        return state

    def stop_run(self):
        "Stop component processing DAQ data"
        try:
            return self.__client.xmlrpc.stopRun()
        except:
            self.__log.error(exc_string())
            return None

    def subrun_events(self, subrun_number):
        "Get the number of events in the specified subrun"
        try:
            evts = self.__client.xmlrpc.getEvents(subrun_number)
            if isinstance(evts, str):
                evts = int(evts[:-1])
            return evts
        except:
            self.__log.error(exc_string())
            return None

    def switch_to_new_run(self, new_run):
        "Switch to new run"
        try:
            return self.__client.xmlrpc.switchToNewRun(new_run)
        except:
            self.__log.error(exc_string())
            return None

    def terminate(self):
        "Terminate component"
        state = self.state
        if state != "idle" and state != "ready" and \
                state != DAQClientState.MISSING and \
                state != DAQClientState.DEAD:
            raise DAQClientException("%s state is %s" % (self, state))

        self.__log.close_final()
        try:
            self.__client.xmlrpc.terminate()
        except:
            # ignore termination exceptions
            pass
