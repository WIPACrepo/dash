#!/usr/bin/env python
"""
Convert a cluster.cfg file into a Python object
"""

from __future__ import print_function

import os
import sys
import traceback

from xml.dom import minidom, Node

from Component import Component
from i3helper import Comparable, reraise_excinfo
from locate_pdaq import find_pdaq_config
from xmlparser import XMLBadFileError, XMLFormatError, XMLParser
from utils.Machineid import Machineid


class ClusterDescriptionFormatError(XMLFormatError):
    "Formatting error"


class ClusterDescriptionException(Exception):
    "General exception"


class ConfigXMLBase(XMLParser):
    def __init__(self, config_dir, config_name, suffix='.xml'):
        self.name = None
        file_name = self.build_path(config_dir, config_name, suffix=suffix)
        if not os.path.exists(config_dir):
            raise XMLBadFileError("Config directory \"%s\" does not exist" %
                                  config_dir)
        if file_name is None:
            raise XMLBadFileError('Cannot find "%s" in "%s"' %
                                  (config_name, config_dir))
        if config_name.endswith(suffix):
            config_name = config_name[:-len(suffix)]

        self.__load_xml(file_name)

        self.__path = file_name
        self.__mtime = os.stat(self.__path).st_mtime
        self.__config_name = config_name

    def __load_xml(self, path):
        try:
            dom = minidom.parse(path)
        except Exception as exc:
            raise XMLFormatError('%s: %s' % (path, str(exc)))

        self.extract_from(dom)

    @property
    def config_name(self):
        return self.__config_name

    def extract_from(self, dom):
        raise NotImplementedError('extract_from method is not implemented')

    def load_if_changed(self, new_path=None):
        if new_path is not None and new_path != self.__path:
            self.__path = new_path
            self.__mtime = 0

        new_mtime = os.stat(self.__path).st_mtime
        if new_mtime == self.__mtime:
            return False

        self.__load_xml(self.__path)

        self.__mtime = new_mtime

        return True


class ClusterComponent(Component):
    def __init__(self, name, num, log_level=None, required=False):
        self.__required = required

        super(ClusterComponent, self).__init__(name, num, log_level=log_level)

    def __str__(self):
        if self.__required:
            rstr = " REQUIRED"
        else:
            rstr = ""

        istr = self.internal_str
        if istr is None:
            istr = ""
        elif istr != "":
            istr = "(%s)" % istr

        return "%s@%s%s%s" % \
            (self.fullname, str(self.log_level), istr, rstr)

    @property
    def has_hitspool_options(self):
        return False

    @property
    def has_jvm_options(self):
        return False

    @property
    def internal_str(self):
        return None

    @property
    def is_control_server(self):
        return self.name == ControlComponent.NAME

    @property
    def is_sim_hub(self):
        return False

    @property
    def required(self):
        return self.__required


class ControlComponent(ClusterComponent):
    NAME = "CnCServer"

    def __init__(self):
        super(ControlComponent, self).__init__(ControlComponent.NAME, 0, None,
                                               True)

    def __str__(self):
        return self.name


class JVMArgs(object):
    def __init__(self, path, is_server, heap_init, heap_max, args, extra_args):
        self.__path = path
        self.__is_server = is_server
        self.__heap_init = heap_init
        self.__heap_max = heap_max
        self.__args = args
        self.__extra_args = extra_args

    def __str__(self):
        outstr = None
        if self.__path is None:
            outstr = "?"
        else:
            outstr = self.__path

        if self.__is_server is not None and self.__is_server:
            outstr += " server"

        if self.__heap_init is not None:
            outstr += " ms=" + self.__heap_init
        if self.__heap_max is not None:
            outstr += " mx=" + self.__heap_max

        if self.__args is not None:
            outstr += " | " + self.__args

        if self.__extra_args is not None:
            outstr += " | " + self.__extra_args

        return outstr

    @property
    def has_data(self):
        return self.__path is not None and self.__is_server is not None and \
          self.__heap_init is not None and self.__heap_max is not None and \
          self.__args is not None and self.__extra_args is not None

    @property
    def args(self):
        return self.__args

    @property
    def extra_args(self):
        return self.__extra_args

    @property
    def heap_init(self):
        return self.__heap_init

    @property
    def heap_max(self):
        return self.__heap_max

    @property
    def is_server(self):
        return self.__is_server is True

    @property
    def path(self):
        return self.__path


class JavaComponent(ClusterComponent):
    def __init__(self, name, num, log_level=None, required=False):
        super(JavaComponent, self).__init__(name, num, log_level=log_level,
                                            required=required)

        self.__jvm = None

    @property
    def has_jvm_options(self):
        return self.__jvm is not None

    @property
    def internal_str(self):
        superstr = super(JavaComponent, self).internal_str
        if self.__jvm is None or not self.__jvm.has_data:
            return superstr

        jvm_str = str(self.__jvm)
        if superstr is None or superstr != "":
            return jvm_str

        if jvm_str is None or jvm_str != "":
            return superstr

        return superstr + " | " + jvm_str

    @property
    def jvm_args(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.args

    @property
    def jvm_extra_args(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.extra_args

    @property
    def jvm_heap_init(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.heap_init

    @property
    def jvm_heap_max(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.heap_max

    @property
    def jvm_path(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been"
                                              " set for %s" % self.fullname)
        return self.__jvm.path

    @property
    def jvm_server(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been"
                                              " set for %s" % self.fullname)
        return self.__jvm.is_server

    @property
    def jvm_string(self):
        if self.__jvm is None:
            return "jvm[???]"
        return str(self.__jvm)

    @property
    def num_replay_files_to_skip(self):
        """Return the number of replay files to skip (None if not specified)"""
        return None

    def set_jvm_options(self, defaults, path, is_server, heap_init, heap_max,
                        args, extra_args):
        # fill in default values for all unspecified JVM quantities
        if path is None:
            path = None if defaults is None \
                   else defaults.find(self.name, 'jvmPath')
            if path is None and defaults is not None and \
               defaults.jvm is not None:
                path = defaults.jvm.path
        if is_server is None:
            is_server = None if defaults is None \
                       else defaults.find(self.name, 'jvmServer')
            if is_server is None and defaults is not None and \
               defaults.jvm is not None:
                is_server = defaults.jvm.is_server
            if is_server is None:
                is_server = False
        if heap_init is None:
            heap_init = None if defaults is None \
                       else defaults.find(self.name, 'jvmHeapInit')
            if heap_init is None and defaults is not None and \
               defaults.jvm is not None:
                heap_init = defaults.jvm.heap_init
        if heap_max is None:
            heap_max = None if defaults is None \
                      else defaults.find(self.name, 'jvmHeapMax')
            if heap_max is None and defaults is not None and \
               defaults.jvm is not None:
                heap_max = defaults.jvm.heap_max
        if args is None:
            args = None if defaults is None \
                   else defaults.find(self.name, 'jvmArgs')
            if args is None and defaults is not None and \
               defaults.jvm is not None:
                args = defaults.jvm.args
        if extra_args is None:
            extra_args = None if defaults is None \
                        else defaults.find(self.name, 'jvmExtraArgs')
            if extra_args is None and defaults is not None and \
               defaults.jvm is not None:
                extra_args = defaults.jvm.extra_args

        self.__jvm = JVMArgs(path, is_server, heap_init, heap_max, args,
                             extra_args)


class HSArgs(object):
    def __init__(self, directory, interval, max_files):
        self.__directory = directory
        self.__interval = interval
        self.__max_files = max_files

    def __str__(self):
        outstr = None
        if self.__directory is None:
            outstr = "?"
        else:
            outstr = self.__directory

        if self.__interval is not None:
            outstr += " ival=%s" % self.__interval
        if self.__max_files is not None:
            outstr += " max=%s" % self.__max_files

        return outstr

    @property
    def directory(self):
        return self.__directory

    @property
    def has_data(self):
        return self.__directory is not None or self.__interval is not None or \
          self.__max_files is not None

    @property
    def interval(self):
        return self.__interval

    @property
    def max_files(self):
        return self.__max_files


class HubComponent(JavaComponent):
    def __init__(self, name, num, log_level=None, required=False):
        super(HubComponent, self).__init__(name, num, log_level=log_level,
                                           required=required)

        self.__hs = None
        self.__ntp_host = None
        self.__alert_email = None

    @property
    def alert_email(self):
        return self.__alert_email

    @property
    def has_hitspool_options(self):
        return True

    @property
    def has_replay_options(self):
        return False

    @property
    def hitspool_directory(self):
        if self.__hs is None:
            raise ClusterDescriptionException("HitSpool options have not" +
                                              " been set")
        return self.__hs.directory

    @property
    def hitspool_interval(self):
        if self.__hs is None:
            raise ClusterDescriptionException("HitSpool options have not" +
                                              " been set")
        return self.__hs.interval

    @property
    def hitspool_max_files(self):
        if self.__hs is None:
            raise ClusterDescriptionException("HitSpool options have not" +
                                              " been set")
        return self.__hs.max_files

    @property
    def internal_str(self):
        if self.__hs is None:
            istr = "hs[???]"
        elif self.__hs.has_data:
            istr = "hs[%s]" % str(self.__hs)
        else:
            istr = ""

        if self.__alert_email is not None:
            istr += " | alert=%s" % self.__alert_email
        if self.__ntp_host is not None:
            istr += " | ntp=%s" % self.__ntp_host

        if istr.startswith(" | "):
            istr = istr[4:]

        return istr

    @property
    def is_real_hub(self):
        return True

    @property
    def ntp_host(self):
        return self.__ntp_host

    def set_hit_spool_options(self, defaults, directory, interval, max_files):
        if directory is None and defaults is not None:
            directory = defaults.find(self.name, 'hitspoolDirectory')
        if interval is None and defaults is not None:
            interval = defaults.find(self.name, 'hitspoolInterval')
        if max_files is None and defaults is not None:
            max_files = defaults.find(self.name, 'hitspoolMaxFiles')
        self.__hs = HSArgs(directory, interval, max_files)

    def set_hub_options(self, defaults, alert_email, ntp_host):
        if ntp_host is None and defaults is not None:
            ntp_host = defaults.find(self.name, 'ntpHost')
        if alert_email is None and defaults is not None:
            alert_email = defaults.find(self.name, 'alertEMail')

        self.__ntp_host = ntp_host
        self.__alert_email = alert_email


class ReplayHubComponent(HubComponent):
    def __init__(self, name, num, log_level=None, required=False):
        super(ReplayHubComponent, self).__init__(name, num,
                                                 log_level=log_level,
                                                 required=required)

        self.__num_to_skip = None

    @property
    def has_replay_options(self):
        return True

    @property
    def internal_str(self):
        istr = super(ReplayHubComponent, self).internal_str
        if self.__num_to_skip is not None:
            istr += " skip=%s" % (self.__num_to_skip, )
        return istr

    @property
    def is_real_hub(self):
        return False

    @property
    def num_replay_files_to_skip(self):
        """
        Return the number of replay files to skip (None if not specified)
        """
        return self.__num_to_skip

    @num_replay_files_to_skip.setter
    def num_replay_files_to_skip(self, value):
        self.__num_to_skip = value


class SimHubComponent(JavaComponent):
    def __init__(self, host, number, priority, if_unused):
        self.__host = host
        self.__number = number
        self.__priority = priority
        self.__if_unused = if_unused

        super(SimHubComponent, self).__init__("SimHub", 0, log_level=None,
                                              required=False)

    def __str__(self):
        if self.__if_unused:
            ustr = "(if_unused)"
        else:
            ustr = ""
        return "%s*%d^%d%s" % \
            (self.__host, self.__number, self.__priority, ustr)

    @property
    def host(self):
        return self.__host

    @property
    def if_unused(self):
        return self.__if_unused

    @property
    def is_sim_hub(self):
        return True

    @property
    def number(self):
        return self.__number

    @property
    def priority(self):
        return self.__priority


class ClusterHost(Comparable):
    def __init__(self, name):
        self.name = name
        self.comp_map = {}
        self.sim_hubs = None
        self.ctl_server = False

    def __str__(self):
        return self.name

    def add_component(self, name, num, log_level, required=False):
        if name.endswith("Hub"):
            comp = HubComponent(name, num, log_level, required)
        elif name == ControlComponent.NAME:
            comp = ControlComponent()
        else:
            comp = JavaComponent(name, num, log_level, required)

        comp_key = comp.fullname
        if comp_key in self.comp_map:
            errmsg = 'Multiple entries for component "%s" in host "%s"' % \
                (comp_key, self.name)
            raise ClusterDescriptionFormatError(errmsg)
        self.comp_map[comp_key] = comp

        return comp

    def add_simulated_hub(self, num, prio, if_unused):
        newhub = SimHubComponent(self, num, prio, if_unused)

        if self.sim_hubs is None:
            self.sim_hubs = []
        for hub in self.sim_hubs:
            if prio == hub.priority:
                errmsg = 'Multiple <simulatedHub> nodes at prio %d for %s' % \
                         (prio, self.name)
                raise ClusterDescriptionFormatError(errmsg)
        self.sim_hubs.append(newhub)
        return newhub

    @property
    def compare_key(self):
        "Return the keys to be used by the Comparable methods"
        return (self.name, self.ctl_server)

    def dump(self, file_handle=None, prefix=None):
        if file_handle is None:
            file_handle = sys.stdout
        if prefix is None:
            prefix = ""

        print("%sHost %s:" % (prefix, self.name), file=file_handle)

        ckeys = sorted(self.comp_map.keys())

        for key in ckeys:
            comp = self.comp_map[key]
            print("%s  Comp %s" % (prefix, str(comp)), file=file_handle)

        if self.sim_hubs is not None:
            for hub in self.sim_hubs:
                if hub.if_unused:
                    ustr = " (if_unused)"
                else:
                    ustr = ""
                print("%s  SimHub*%d prio %d%s" %
                      (prefix, hub.number, hub.priority, ustr),
                      file=file_handle)

        if self.ctl_server:
            print("%s  ControlServer" % prefix, file=file_handle)

    @property
    def components(self):
        return self.comp_map.values()

    @property
    def is_control_server(self):
        return self.ctl_server

    def merge(self, host):
        if self.name != host.name:
            raise AttributeError("Cannot merge host \"%s\" entry into \"%s\"" %
                                 (host.name, self.name))

        if host.ctl_server:
            self.ctl_server = True

        for comp in list(host.comp_map.values()):
            key = comp.fullname
            if key in self.comp_map:
                errmsg = 'Multiple entries for component "%s" in host "%s"' % \
                         (key, host.name)
                raise ClusterDescriptionFormatError(errmsg)
            self.comp_map[key] = comp

        if host.sim_hubs is not None:
            if self.sim_hubs is None:
                self.sim_hubs = []
            for scomp in host.sim_hubs:
                self.sim_hubs.append(scomp)

    def set_control_server(self):
        self.ctl_server = True


class ClusterDefaults(object):
    def __init__(self):
        self.components = {}
        self.hitspool = HSArgs(None, None, None)
        self.jvm = JVMArgs(None, None, None, None, None, None)
        self.loglevel = ClusterDescription.DEFAULT_LOG_LEVEL

    def __str__(self):
        if not self.components:
            cstr = ""
        else:
            cstr = ", " + str(self.components)

        return "ClusterDefaults[hs %s, jvm %s, loglvl %s, args %s]" % \
            (self.hitspool, self.jvm, self.loglevel, cstr)

    def find(self, comp_name, val_name):
        if comp_name is not None and \
                self.components is not None and \
                comp_name in self.components and \
                val_name in self.components[comp_name]:
            return self.components[comp_name][val_name]

        val = None
        if val_name == 'hitspoolDirectory':
            val = self.hitspool.directory
        elif val_name == 'hitspoolInterval':
            val = self.hitspool.interval
        elif val_name == 'hitspoolMaxFiles':
            val = self.hitspool.max_files
        elif val_name == 'jvmPath':
            val = self.jvm.path
        elif val_name == 'jvmServer':
            val = self.jvm.is_server
        elif val_name == 'jvmHeapInit':
            val = self.jvm.heap_init
        elif val_name == 'jvmHeapMax':
            val = self.jvm.heap_max
        elif val_name == 'jvmArgs':
            val = self.jvm.args
        elif val_name == 'jvmExtraArgs':
            val = self.jvm.extra_args
        elif val_name == 'logLevel':
            val = self.loglevel

        return val


class ClusterDescription(ConfigXMLBase):
    LOCAL = "localhost"
    PDAQ2 = "pdaq2"
    SPS = "sps"
    SPTS = "spts"
    MDFL = "mdfl"

    DEFAULT_DATA_DIR = "/mnt/data/pdaqlocal"
    DEFAULT_LOG_DIR = "/mnt/data/pdaq/log"
    DEFAULT_LOG_LEVEL = "WARN"

    DEFAULT_PKGSTAGE_DIR = "/software/stage/pdaq/dependencies/tar"
    DEFAULT_PKGINSTALL_DIR = "/software/pdaq"

    def __init__(self, config_dir=None, config_name=None, suffix='.cfg'):
        self.name = None
        self.__host_map = None
        self.__defaults = None

        self.__spade_log_dir = None
        self.__log_dir_copies = None
        self.__daq_data_dir = None
        self.__daq_log_dir = None
        self.__pkg_stage_dir = None
        self.__pkg_install_dir = None

        self.__default_hs = HSArgs(None, None, None)
        self.__default_jvm = JVMArgs(None, None, None, None, None, None)
        self.__default_log_level = self.DEFAULT_LOG_LEVEL

        if config_name is None:
            config_name = self.get_cluster_name()

        if config_dir is None:
            config_dir = find_pdaq_config()

        try:
            super(ClusterDescription, self).__init__(config_dir, config_name,
                                                     suffix)
        except XMLBadFileError:
            saved_exc = sys.exc_info()

            if not config_name.endswith('.cfg'):
                retry_name = config_name
            else:
                retry_name = config_name[:-4]

            if not retry_name.endswith('-cluster'):
                retry_name += '-cluster'

            try:
                super(ClusterDescription, self).__init__(config_dir,
                                                         retry_name, suffix)
                config_name = retry_name
            except XMLBadFileError:
                reraise_excinfo(saved_exc)

        derived_name, _ = os.path.splitext(os.path.basename(config_name))
        if derived_name.endswith("-cluster"):
            derived_name = derived_name[:-8]
        if derived_name != self.name:
            self.name = derived_name

    def __str__(self):
        return self.name

    @classmethod
    def __parse_component_node(cls, cluster_name, defaults, host, node):
        "Parse a <component> node from a cluster configuration file"
        name = cls.get_value(node, 'name')
        if name is None:
            errmsg = ('Cluster "%s" host "%s" has <component> node' +
                      ' without "name" attribute') % (cluster_name, host.name)
            raise ClusterDescriptionFormatError(errmsg)

        id_str = cls.get_value(node, 'id', '0')
        try:
            num = int(id_str)
        except ValueError:
            errmsg = ('Cluster "%s" host "%s" component '
                      '"%s" has bad ID "%s"') % \
                (cluster_name, host.name, name, id_str)
            raise ClusterDescriptionFormatError(errmsg)

        # look for optional logLevel
        loglvl = cls.get_value(node, 'logLevel')
        if loglvl is None:
            loglvl = defaults.find(name, 'logLevel')
            if loglvl is None:
                loglvl = defaults.loglevel

        # look for "required" attribute
        req_str = cls.get_value(node, 'required')
        required = cls.parse_boolean_string(req_str) is True

        comp = host.add_component(name, num, loglvl, required=required)

        (jvm_path, jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
         jvm_extra_args) = cls.__parse_jvm_nodes(node)
        comp.set_jvm_options(defaults, jvm_path, jvm_server, jvm_heap_init,
                             jvm_heap_max, jvm_args, jvm_extra_args)

        if comp.is_real_hub:
            alert_email = cls.get_value(node, 'alertEMail')
            ntp_host = cls.get_value(node, 'ntpHost')

            comp.set_hub_options(defaults, alert_email, ntp_host)

            (hs_dir, hs_interval, hs_max_files) = cls.__parse_hs_nodes(node)
            comp.set_hit_spool_options(defaults, hs_dir, hs_interval,
                                       hs_max_files)

    def __parse_default_nodes(self, clu_name, defaults, node):
        """load JVM defaults"""
        (hs_dir, hs_ival, hs_maxfiles) = self.__parse_hs_nodes(node)
        defaults.hitspool = HSArgs(hs_dir, hs_ival, hs_maxfiles)

        (path, is_server, heap_init, heap_max, args, extra_args) = \
            self.__parse_jvm_nodes(node)
        defaults.jvm = JVMArgs(path, is_server, heap_init, heap_max, args,
                               extra_args)

        for kid in node.childNodes:
            if kid.nodeType != Node.ELEMENT_NODE:
                continue

            if kid.nodeName == 'logLevel':
                defaults.loglevel = self.get_child_text(kid)
            elif kid.nodeName == 'component':
                name = self.get_value(kid, 'name')
                if name is None:
                    errmsg = ('Cluster "%s" default section has <component>' +
                              ' node without "name" attribute') % clu_name
                    raise ClusterDescriptionFormatError(errmsg)

                if name not in defaults.components:
                    defaults.components[name] = {}

                (hs_dir, hs_ival, hs_maxfiles) = self.__parse_hs_nodes(kid)
                if hs_dir is not None:
                    defaults.components[name]['hitspoolDirectory'] = hs_dir
                if hs_ival is not None:
                    defaults.components[name]['hitspoolInterval'] = hs_ival
                if hs_maxfiles is not None:
                    defaults.components[name]['hitspoolMaxFiles'] = hs_maxfiles

                (path, is_server, heap_init, heap_max, args, extra_args) = \
                    self.__parse_jvm_nodes(kid)
                if path is not None:
                    defaults.components[name]['jvmPath'] = path
                if is_server is not None:
                    defaults.components[name]['jvmServer'] = is_server
                if heap_init is not None:
                    defaults.components[name]['jvmHeapInit'] = heap_init
                if heap_max is not None:
                    defaults.components[name]['jvmHeapMax'] = heap_max
                if args is not None:
                    defaults.components[name]['jvmArgs'] = args
                if extra_args is not None:
                    defaults.components[name]['jvmExtraArgs'] = extra_args

                for kidkid in kid.childNodes:
                    if kidkid.nodeType == Node.ELEMENT_NODE and \
                       kidkid.nodeName == 'logLevel':
                        defaults.components[name]['logLevel'] = \
                            self.get_child_text(kidkid)
                        continue

                    if kidkid.nodeType == Node.ELEMENT_NODE and \
                       kidkid.nodeName == 'alertEMail':
                        defaults.components[name]['alertEMail'] = \
                            self.get_child_text(kidkid)
                        continue

                    if kidkid.nodeType == Node.ELEMENT_NODE and \
                       kidkid.nodeName == 'ntpHost':
                        defaults.components[name]['ntpHost'] = \
                            self.get_child_text(kidkid)
                        continue

    @classmethod
    def __parse_host_nodes(cls, name, defaults, host_nodes):
        host_map = {}
        comp_to_host = {}

        for node in host_nodes:
            hostname = cls.get_value(node, 'name')
            if hostname is None:
                errmsg = ('Cluster "%s" has <host> node without "name"' +
                          ' attribute') % name
                raise ClusterDescriptionFormatError(errmsg)

            host = ClusterHost(hostname)

            for kid in node.childNodes:
                if kid.nodeType != Node.ELEMENT_NODE:
                    continue

                if kid.nodeName == 'component':
                    cls.__parse_component_node(name, defaults, host, kid)
                elif kid.nodeName == 'controlServer':
                    host.set_control_server()
                elif kid.nodeName == 'simulatedHub':
                    cls.__parse_simhub_node(name, defaults, host, kid)

            # add host to internal host dictionary
            if hostname not in host_map:
                host_map[hostname] = host
            else:
                host_map[hostname].merge(host)

            for comp in host.components:
                comp_key = comp.fullname
                if comp_key in comp_to_host:
                    errmsg = 'Multiple entries for component "%s"' % comp_key
                    raise ClusterDescriptionFormatError(errmsg)
                comp_to_host[comp_key] = host

        return host_map

    @classmethod
    def __parse_hs_nodes(cls, node):
        # create all hitspool-related variables
        hs_dir = None
        interval = None
        max_files = None

        # look for jvm node
        for hs_node in cls.get_child_nodes(node, 'hitspool'):
            tmp_dir = cls.get_attribute(hs_node, 'directory')
            if tmp_dir is not None:
                hs_dir = os.path.expanduser(tmp_dir)
            tmp_str = cls.get_attribute(hs_node, 'interval',
                                        default_val=interval)
            if tmp_str is not None:
                interval = float(tmp_str)
            tmp_str = cls.get_attribute(hs_node, 'maxfiles',
                                        default_val=max_files)
            if tmp_str is not None:
                max_files = int(tmp_str)

        return (hs_dir, interval, max_files)

    @classmethod
    def __parse_jvm_nodes(cls, node):
        # create all JVM-related variables
        path = None
        is_server = None
        heap_init = None
        heap_max = None
        args = None
        extra_args = None

        # look for jvm node
        for jvm_node in cls.get_child_nodes(node, 'jvm'):
            tmp_path = cls.get_attribute(jvm_node, 'path')
            if tmp_path is not None:
                path = os.path.expanduser(tmp_path)
            tmp_srvr = cls.get_attribute(jvm_node, 'server')
            if tmp_srvr is not None:
                is_server = cls.parse_boolean_string(tmp_srvr)
            heap_init = cls.get_attribute(jvm_node, 'heapInit',
                                          default_val=heap_init)
            heap_max = cls.get_attribute(jvm_node, 'heapMax',
                                         default_val=heap_max)
            args = cls.get_attribute(jvm_node, 'args')
            extra_args = cls.get_attribute(jvm_node, 'extraArgs',
                                           default_val=extra_args)

        return (path, is_server, heap_init, heap_max, args, extra_args)

    @classmethod
    def __parse_simhub_node(cls, cluster_name, defaults, host, node):
        "Parse a <simulatedHub> node from a cluster configuration file"
        num_str = cls.get_value(node, 'number', '0')
        try:
            num = int(num_str)
        except ValueError:
            errmsg = ('Cluster "%s" host "%s" has <simulatedHub> node with' +
                      ' bad number "%s"') % (cluster_name, host.name, num_str)
            raise ClusterDescriptionFormatError(errmsg)

        prio_str = cls.get_value(node, 'priority')
        if prio_str is None:
            errmsg = ('Cluster "%s" host "%s" has <simulatedHub> node' +
                      ' without "priority" attribute') % \
                      (cluster_name, host.name)
            raise ClusterDescriptionFormatError(errmsg)
        try:
            prio = int(prio_str)
        except ValueError:
            errmsg = ('Cluster "%s" host "%s" has <simulatedHub> node' +
                      ' with bad priority "%s"') % \
                      (cluster_name, host.name, prio_str)
            raise ClusterDescriptionFormatError(errmsg)

        if_str = cls.get_value(node, 'ifUnused')
        if_unused = cls.parse_boolean_string(if_str) is True

        comp = host.add_simulated_hub(num, prio, if_unused)

        (jvm_path, jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
         jvm_extra_args) = cls.__parse_jvm_nodes(node)
        comp.set_jvm_options(defaults, jvm_path, jvm_server, jvm_heap_init,
                             jvm_heap_max, jvm_args, jvm_extra_args)

        return host

    @property
    def daq_data_dir(self):
        if self.__daq_data_dir is None:
            return self.DEFAULT_DATA_DIR
        return self.__daq_data_dir

    @property
    def daq_log_dir(self):
        if self.__daq_log_dir is None:
            return self.DEFAULT_LOG_DIR
        return self.__daq_log_dir

    def default_alert_email(self, comp_name=None):
        return self.__defaults.find(comp_name, 'alertEMail')

    def default_hs_directory(self, comp_name=None):
        return self.__defaults.find(comp_name, 'hitspoolDirectory')

    def default_hs_interval(self, comp_name=None):
        return self.__defaults.find(comp_name, 'hitspoolInterval')

    def default_hs_max_files(self, comp_name=None):
        return self.__defaults.find(comp_name, 'hitspoolMaxFiles')

    def default_jvm_args(self, comp_name=None):
        return self.__defaults.find(comp_name, 'jvmArgs')

    def default_jvm_extra_args(self, comp_name=None):
        return self.__defaults.find(comp_name, 'jvmExtraArgs')

    def default_jvm_heap_init(self, comp_name=None):
        return self.__defaults.find(comp_name, 'jvmHeapInit')

    def default_jvm_heap_max(self, comp_name=None):
        return self.__defaults.find(comp_name, 'jvmHeapMax')

    def default_jvm_path(self, comp_name=None):
        return self.__defaults.find(comp_name, 'jvmPath')

    def default_jvm_server(self, comp_name=None):
        return self.__defaults.find(comp_name, 'jvmServer')

    def default_log_level(self, comp_name=None):
        return self.__defaults.find(comp_name, 'logLevel')

    def default_ntp_host(self, comp_name=None):
        return self.__defaults.find(comp_name, 'ntpHost')

    def dump(self, file_handle=None, prefix=None):
        if file_handle is None:
            file_handle = sys.stdout
        if prefix is None:
            prefix = ""

        print("%sDescription %s" % (prefix, self.name), file=file_handle)
        if self.__spade_log_dir is not None:
            print("%s  SPADE log directory: %s" %
                  (prefix, self.__spade_log_dir), file=file_handle)
        if self.__log_dir_copies is not None:
            print("%s  Copied log directory: %s" %
                  (prefix, self.__log_dir_copies), file=file_handle)
        if self.__daq_data_dir is not None:
            print("%s  DAQ data directory: %s" %
                  (prefix, self.__daq_data_dir), file=file_handle)
        if self.__daq_log_dir is not None:
            print("%s  DAQ log directory: %s" %
                  (prefix, self.__daq_log_dir), file=file_handle)
        if self.__pkg_stage_dir is not None:
            print("%s  Package staging directory: %s" %
                  (prefix, self.__pkg_stage_dir), file=file_handle)
        if self.__pkg_install_dir is not None:
            print("%s  Package installation directory: %s" %
                  (prefix, self.__pkg_install_dir), file=file_handle)

        if self.__default_hs is not None:
            if self.__default_hs.directory is not None:
                print("%s  Default HS directory: %s" %
                      (prefix, self.__default_hs.directory), file=file_handle)
            if self.__default_hs.interval is not None:
                print("%s  Default HS interval: %s" %
                      (prefix, self.__default_hs.interval), file=file_handle)
            if self.__default_hs.max_files is not None:
                print("%s  Default HS max files: %s" %
                      (prefix, self.__default_hs.max_files), file=file_handle)

        if self.__default_jvm is not None:
            if self.__default_jvm.path is not None:
                print("%s  Default Java executable: %s" %
                      (prefix, self.__default_jvm.path), file=file_handle)
            if self.__default_jvm.is_server is not None:
                print("%s  Default Java server flag: %s" %
                      (prefix, self.__default_jvm.is_server), file=file_handle)
            if self.__default_jvm.heap_init is not None:
                print("%s  Default Java heap init: %s" %
                      (prefix, self.__default_jvm.heap_init), file=file_handle)
            if self.__default_jvm.heap_max is not None:
                print("%s  Default Java heap max: %s" %
                      (prefix, self.__default_jvm.heap_max), file=file_handle)
            if self.__default_jvm.args is not None:
                print("%s  Default Java arguments: %s" %
                      (prefix, self.__default_jvm.args), file=file_handle)
            if self.__default_jvm.extra_args is not None:
                print("%s  Default Java extra arguments: %s" %
                      (prefix, self.__default_jvm.extra_args),
                      file=file_handle)

        if self.__default_log_level is not None:
            print("%s  Default log level: %s" %
                  (prefix, self.__default_log_level), file=file_handle)

        tmp_comps = self.__defaults.components
        if tmp_comps is None or \
          len(tmp_comps) == 0:  # pylint: disable=len-as-condition
            print("  **No default components**", file=file_handle)
        else:
            print("  Default components:", file=file_handle)
            for comp in self.__defaults.components:
                print("%s    %s:" % (prefix, comp), file=file_handle)

                comp_dflts = self.__defaults.components[comp]
                if 'hitspoolDirectory' in comp_dflts:
                    print("%s      HS directory: %s" %
                          (prefix, comp_dflts['hitspoolDirectory']),
                          file=file_handle)
                if 'hitspoolInterval' in comp_dflts:
                    print("%s      HS interval: %s" %
                          (prefix, comp_dflts['hitspoolInterval']),
                          file=file_handle)
                if 'hitspoolMaxFiles' in comp_dflts:
                    print("%s      HS max files: %s" %
                          (prefix, comp_dflts['hitspoolMaxFiles']),
                          file=file_handle)

                if 'jvmPath' in comp_dflts:
                    print("%s      Java executable: %s" %
                          (prefix, comp_dflts['jvmPath']), file=file_handle)
                if 'jvmServer' in comp_dflts:
                    print("%s      Java server flag: %s" %
                          (prefix, comp_dflts['jvmServer']), file=file_handle)
                if 'jvmHeapInit' in comp_dflts:
                    print("%s      Java initial heap size: %s" %
                          (prefix, comp_dflts['jvmHeapInit']),
                          file=file_handle)
                if 'jvmHeapMax' in comp_dflts:
                    print("%s      Java maximum heap size: %s" %
                          (prefix, comp_dflts['jvmHeapMax']), file=file_handle)
                if 'jvmArgs' in comp_dflts:
                    print("%s      Java arguments: %s" %
                          (prefix, comp_dflts['jvmArgs']), file=file_handle)
                if 'jvmExtraArgs' in comp_dflts:
                    print("%s      Java extra arguments: %s" %
                          (prefix, comp_dflts['jvmExtraArgs']),
                          file=file_handle)

                if 'logLevel' in comp_dflts:
                    print("%s      Log level: %s" %
                          (prefix, comp_dflts['logLevel']), file=file_handle)

        if self.__host_map is not None:
            for key in sorted(self.__host_map.keys()):
                self.__host_map[key].dump(file_handle=file_handle,
                                          prefix=prefix + "  ")

    def extract_from(self, dom):
        "Extract all necessary information from a cluster configuration file"
        clu_name = 'cluster'
        kids = dom.getElementsByTagName(clu_name)
        if len(kids) < 1:  # pylint: disable=len-as-condition
            raise XMLFormatError('No <%s> node found' % clu_name)
        elif len(kids) > 1:
            raise XMLFormatError('Multiple <%s> nodes found' % clu_name)

        cluster = kids[0]

        name = self.get_value(cluster, 'name')

        defaults = ClusterDefaults()

        dflt_nodes = cluster.getElementsByTagName('default')
        for node in dflt_nodes:
            self.__parse_default_nodes(name, defaults, node)

        host_nodes = cluster.getElementsByTagName('host')
        if len(host_nodes) < 1:  # pylint: disable=len-as-condition
            errmsg = 'No hosts defined for cluster "%s"' % name
            raise ClusterDescriptionFormatError(errmsg)

        host_map = self.__parse_host_nodes(name, defaults, host_nodes)
        self.name = name
        self.__defaults = defaults
        self.__host_map = host_map

        self.__spade_log_dir = self.get_value(cluster, 'logDirForSpade')
        # expand tilde
        if self.__spade_log_dir is not None:
            self.__spade_log_dir = os.path.expanduser(self.__spade_log_dir)

        self.__log_dir_copies = self.get_value(cluster, 'logDirCopies')
        if self.__log_dir_copies is not None:
            self.__log_dir_copies = os.path.expanduser(self.__log_dir_copies)

        self.__daq_data_dir = self.get_value(cluster, 'daqDataDir')
        if self.__daq_data_dir is not None:
            self.__daq_data_dir = os.path.expanduser(self.__daq_data_dir)

        self.__daq_log_dir = self.get_value(cluster, 'daqLogDir')
        if self.__daq_log_dir is not None:
            self.__daq_log_dir = os.path.expanduser(self.__daq_log_dir)

        self.__pkg_stage_dir = self.get_value(cluster, 'packageStageDir')
        if self.__pkg_stage_dir is not None:
            self.__pkg_stage_dir = os.path.expanduser(self.__pkg_stage_dir)

        self.__pkg_install_dir = self.get_value(cluster, 'packageInstallDir')
        if self.__pkg_install_dir is not None:
            self.__pkg_install_dir = os.path.expanduser(self.__pkg_install_dir)

    @classmethod
    def get_cluster_name(cls):
        """
        Determine the cluster name using the local host name.
        Returned values are "sps", "spts", "spts64", or "localhost".
        """

        mid = Machineid()
        if mid.is_sps_cluster:
            return cls.SPS
        if mid.is_spts_cluster:
            return cls.SPTS
        if mid.is_mdfl_cluster:
            return cls.MDFL

        return cls.LOCAL

    @classmethod
    def get_live_db_name(cls):
        live_config_name = ".i3live.conf"

        path = os.path.join(os.environ["HOME"], live_config_name)
        if os.path.exists(path):
            with open(path, "r") as fin:
                for line in fin:
                    if line.startswith("["):
                        ridx = line.find("]")
                        if ridx < 0:
                            # ignore line with bad section marker
                            continue

                        section = line[1:ridx]
                        continue

                    if section != "livecontrol":
                        continue

                    pos = line.find("=")
                    if pos < 0:
                        continue

                    if line[:pos].strip() != "dbname":
                        continue

                    return line[pos + 1:].strip()

        return None

    def host(self, name):
        if name not in self.__host_map:
            return None

        return self.__host_map[name]

    @property
    def hosts(self):
        for host in self.__host_map:
            yield host

    @property
    def host_component_pairs(self):
        "Generate a stream of (host, component) tuples"
        for host in self.__host_map:
            for comp in self.__host_map[host].components:
                yield (host, comp)
            if self.__host_map[host].is_control_server:
                yield (host, ControlComponent())

    @property
    def host_sim_hub_pairs(self):
        "Generate a stream of (host, simhub_component) tuples"
        for host in self.__host_map:
            if self.__host_map[host].sim_hubs is not None:
                for sim in self.__host_map[host].sim_hubs:
                    yield (host, sim)

    @property
    def log_dir_for_spade(self):
        return self.__spade_log_dir

    @property
    def log_dir_copies(self):
        return self.__log_dir_copies

    @property
    def package_stage_dir(self):
        if self.__pkg_stage_dir is None:
            return self.DEFAULT_PKGSTAGE_DIR
        return self.__pkg_stage_dir

    @property
    def package_install_dir(self):
        if self.__pkg_install_dir is None:
            return self.DEFAULT_PKGINSTALL_DIR
        return self.__pkg_install_dir


def main():
    "Main program"

    def try_cluster(config_dir, path=None):
        if path is None:
            cluster = ClusterDescription(config_dir)
        else:
            dir_name = os.path.dirname(path)
            if dir_name is None or \
              len(dir_name) == 0:  # pylint: disable=len-as-condition
                dir_name = config_dir
                base_name = path
            else:
                base_name = os.path.basename(path)

            try:
                cluster = ClusterDescription(dir_name, base_name)
            except KeyboardInterrupt:
                return
            except NotImplementedError:
                print('For %s:' % path, file=sys.stderr)
                traceback.print_exc()
                return
            except:  # pylint: disable=bare-except
                print('For %s:' % path, file=sys.stderr)
                traceback.print_exc()
                return

        print('Saw description %s' % cluster.name)
        cluster.dump()

    config_dir = find_pdaq_config()

    if len(sys.argv) == 1:
        try_cluster(config_dir)
    else:
        for name in sys.argv[1:]:
            try_cluster(config_dir, name)


if __name__ == '__main__':
    main()
