#!/usr/bin/env python

import os
import sys

from DefaultDomGeometry import BadFileError, DefaultDomGeometryReader, \
    ProcessError
from locate_pdaq import find_pdaq_config
from xml_dict import get_attrib, get_value, xml_dict
from utils.Machineid import Machineid
from config.validate_configs import validate_configs
from RunCluster import RunCluster
from Component import Component
from CachedConfigName import CachedConfigName

# config exceptions
from DAQConfigExceptions import DAQConfigException
from DAQConfigExceptions import BadComponentName
from DAQConfigExceptions import BadDOMID
from DAQConfigExceptions import ConfigNotSpecifiedException
from DAQConfigExceptions import DOMNotInConfigException


class FindConfigDir:
    """A utility class to hold the pdaq configuration file
    directory.  This class is here so the file can be easily overridden
    and pointed to test configs in dash/src/..."""
    CONFIG_DIR = find_pdaq_config()

    def __init__(self):
        raise TypeError("Meant to be a utility class, do not instantiate")

    @classmethod
    def config_dir(cls):
        """Return the configuration file directory."""
        return cls.CONFIG_DIR


class HubIdUtils:
    """The logic contained in here was duplicated in multiple
    places.  Instead of duplication, concentrate it in one place"""

    def __init__(self):
        raise TypeError("Meant to be a utility class, do not instantiate")

    @staticmethod
    def is_deep_core(hub_id):
        """Returns true for a deep core string."""
        return (hub_id % 1000) > 78 and (hub_id % 1000) < 200

    @staticmethod
    def is_icetop(hub_id):
        """Returns true for an icetop string"""
        return (hub_id % 1000) >= 200

    @staticmethod
    def is_in_ice(hub_id):
        """Returns true if the hub_id argument belongs
        to an in ice string"""
        return (hub_id % 1000) < 200

    @staticmethod
    def get_hub_name(num):
        """Get the standard representation for a hub number"""
        base_num = int(num) % 1000
        if base_num > 0 and base_num < 100:
            return "%02d" % base_num
        if base_num > 200 and base_num < 220:
            return "%02dt" % (base_num - 200)
        return "?%d?" % base_num


class StringHub(Component):
    """String hub data from a run configuration file"""
    def __init__(self, xdict, hub_id, inferred=False):
        self.xdict = xdict
        self.hub_id = int(hub_id)
        self.inferred = inferred
        super(StringHub, self).__init__("stringHub", hub_id)

    def isDeepCore(self):
        return HubIdUtils.is_deep_core(self.__id)

    def isIceTop(self):
        return HubIdUtils.is_icetop(self.__id)

    def isInIce(self):
        return HubIdUtils.is_in_ice(self.__id)


class ReplayHub(Component):
    "Replay hub data from a run configuration file"

    def __init__(self, xdict, base_dir, old_style):
        self.base_dir = base_dir
        self.xdict = xdict
        hub_id = int(get_attrib(xdict, 'hub'))
        if not old_style:
            self.host = get_attrib(xdict, 'host')
            if hub_id < 200:
                self.hitFile = "ichub%02d" % hub_id
            else:
                self.hitFile = "ithub%02d" % (hub_id - 200)
        else:
            self.host = None
            self.hitFile = get_attrib(xdict, 'source')

        super(ReplayHub, self).__init__("replayHub", hub_id)

    def isDeepCore(self):
        return HubIdUtils.is_deep_core(self.__id)

    def isIceTop(self):
        return HubIdUtils.is_icetop(self.__id)

    def isInIce(self):
        return HubIdUtils.is_in_ice(self.__id)


class ConfigObject(object):
    def __init__(self, fname):
        self.xdict = None
        self.xml_runcfg = None
        self.__filename = fname

    def basename(self):
        base = os.path.basename(self.filename)
        base, ext = os.path.splitext(base)
        return base

    @property
    def filename(self):
        """Return the filename property.
        Should include full path information"""
        return self.__filename

    @filename.setter
    def filename(self, filename):
        """Take a config filename, try to find it and parse it.
        In case the file is not accessible raise the BadFileError"""
        self.__filename = self.find_config(filename)
        try:
            self.xml_runcfg = xml_dict(self.__filename)
        except IOError:
            raise BadFileError("Cannot read xml file '%s'" % self.__filename)
        self.xdict = self.xml_runcfg.xml_dict

    @filename.deleter
    def filename(self):
        raise AttributeError("Do Not Delete Filename Attribute")

    @classmethod
    def find_config(cls, filename):
        """Return a tuple for the top level
        configuration directory and a completed filename"""

        config_dir = FindConfigDir.config_dir()

        basepath, ext = os.path.splitext(filename)

        if ext.lower() != '.xml':
            return (config_dir, "%s.xml" % basepath)
        else:
            return (config_dir, os.path.basename(filename))


class TriggerConfig(ConfigObject):
    def __init__(self, trig_config_dict):
        fname = get_value(trig_config_dict)
        self.initial_dict = trig_config_dict

        super(TriggerConfig, self).__init__(fname)

        self.filename = fname

    @classmethod
    def find_config(cls, filename):
        """given a dom config filename
        look for it and generate a path"""

        (config_dir, basename) = super(TriggerConfig,
                                       cls).find_config(filename)

        trig_config_dir = os.path.join(config_dir, 'trigger')

        return os.path.join(trig_config_dir, basename)


class RunDom(dict):
    """Note that the majority of the methods
    exposed from the old code were for setting state from
    parsing code.  Setting values from parsing code is no
    longer needed"""

    DEFAULT_DOM_GEOMETRY = None

    def __init__(self, dom_dict):
        self.dom_dict = dom_dict

        self.__id = long(self['mbid'], 16)
        try:
            self.__name = self['name']
        except AttributeError, ex:
            self.__name = None

        dom_id_to_dom = RunDom.__load_dom_id_map()
        dom_geom = dom_id_to_dom[self['mbid']]

        self.__string = dom_geom.string()
        self.__pos = dom_geom.pos()

        dict.__init__(self)

    def __str__(self):
        return "%s" % self['mbid']

    @classmethod
    def __load_dom_id_map(cls):
        if cls.DEFAULT_DOM_GEOMETRY is None:
            cls.DEFAULT_DOM_GEOMETRY = \
                DefaultDomGeometryReader.parse(translateDoms=True)

        return cls.DEFAULT_DOM_GEOMETRY.getDomIdToDomDict()

    def __getitem__(self, key):
        """Maybe an odd overloading of a python dictionary,
        if you access rundom['X'] you can get the attrib or value
        for that dom."""
        try:
            attrib = get_attrib(self.dom_dict, key)
            return attrib
        except AttributeError, attr_err:
            if key in self.dom_dict['__children__']:
                val = get_value(self.dom_dict['__children__'][key])
                return val

            raise attr_err

    # Technically not really required, but keep
    # the signature the same for these methods
    def id(self):
        return self.__id

    def string(self):
        return self.__string

    def pos(self):
        return self.__pos

    def name(self):
        return self.__name


class DomConfig(ConfigObject):
    def __init__(self, fname):
        self.rundoms = []
        self.string_map = {}
        self.__comps = []
        # set the filename property
        super(DomConfig, self).__init__(fname)
        self.hub_id = None
        self.filename = fname

    @classmethod
    def find_config(cls, filename):
        """given a dom config filename
        look for it and generate a path"""

        (config_dir, basename) = super(DomConfig, cls).find_config(filename)

        dom_config_dir = os.path.join(config_dir, 'domconfigs')

        return os.path.join(dom_config_dir, basename)

    @ConfigObject.filename.setter
    def filename(self, filename):
        ConfigObject.filename.__set__(self, filename)

        self.string_map = {}

        if type(self.xdict) == dict and \
                type(self.xdict['domConfigList']) == dict and \
                type(self.xdict['domConfigList']['__children__']) == dict and \
                type(self.xdict['domConfigList']['__children__']['domConfig']) \
                == list:
            try:
                dom_configs = \
                    self.xdict['domConfigList']['__children__']['domConfig']

                for entry in dom_configs:
                    rd = RunDom(entry)
                    self.rundoms.append(rd)

                    string = rd.string()
                    if string not in self.string_map:
                        self.string_map[string] = []
                        self.hub_id = string
                    self.string_map[string].append(rd)

            except KeyError:
                raise AttributeError("File: %s not valid" % filename)

        # check to see if there is more than one string in this
        # config file
        if len(self.string_map) > 1:
            raise DAQConfigException("Found %d strings in domconfig %s: %s" %
                                     (len(self.string_map), filename,
                                      self.string_map.keys()))


class DAQConfig(ConfigObject):
    def __init__(self, filename, strict=False):
        self.__comps = []
        self.dom_cfgs = []

        self.comps = []
        self.other_objs = []
        self.run_comps = []
        self.trig_cfg = None
        self.stringhub_map = {}
        self.replay_hubs = []
        self.strict = strict

        super(DAQConfig, self).__init__(filename)

        self.filename = filename

    def validate(self):
        """The syntax of a file is verified with the
        rng validation parser, but there are a few things
        not validated"""

        if len(self.stringhub_map) == 0 and len(self.replay_hubs) == 0:
            raise ProcessError("No doms or replayHubs found in %s"
                               % self.filename)

        if not self.trig_cfg:
            raise ProcessError("No <triggerConfig> found in %s"
                               % self.filename)

        in_ice_hub, in_ice_trig, \
            ice_top_hub, ice_top_trig = (False, False, False, False)

        for c in self.comps:
            if c.isHub():
                if c.isInIce():
                    in_ice_hub = True
                else:
                    ice_top_hub = True
            elif c.isTrigger():
                lname = c.name().lower()
                if lname.startswith("inice"):
                    in_ice_trig = True
                elif lname.startswith("icetop"):
                    ice_top_trig = True

        if in_ice_hub and not in_ice_trig:
            raise ProcessError("Found in-ice hubs but no in-ice trigger in %s"
                               % self.filename)

        if not in_ice_hub and in_ice_trig:
            raise ProcessError("Found in-ice trigger but not in-ice hubs in %s"
                               % self.filename)

        if ice_top_hub and not ice_top_trig:
            raise ProcessError("Found icetop hubs but no icetop trigger in %s"
                               % self.filename)

        if not ice_top_hub and ice_top_trig:
            raise ProcessError("Found icetop trigger but no icetop hubs in %s"
                               % self.filename)

    @classmethod
    def showList(cls, config_dir=None, config_name=None):
        if not config_dir:
            config_dir = find_pdaq_config()

        if not os.path.exists(config_dir):
            raise DAQConfigException("Could not find config dir %s" %
                                     config_dir)

        if not config_name:
            config_name = CachedConfigName.getConfigToUse(None, False, True)

        cfgs = []

        for fname in os.listdir(config_dir):
            cfg = os.path.basename(fname[:-4])
            if fname.endswith(".xml") and cfg != 'default-dom-geometry':
                cfgs.append(cfg)

        cfgs.sort()
        for cname in cfgs:
            mark = "   "
            if not config_name:
                mark = ""
            elif cname == config_name:
                mark = "=> "

            try:
                print "%s%-60s" % (mark, cname)
            except IOError:
                break

    def __getBoolean(self, name, attr_name):
        """Extract a period specification from the configuration"""
        for key, value in self.other_objs:
            if key == name and type(value) == list:
                for v in value:
                    try:
                        dstr = get_attrib(v, attr_name)
                        if dstr is None:
                            return False
                        dstr = dstr.lower()
                        return dstr == "true" or dstr == "yes"
                    except (AttributeError, ValueError):
                        pass

        return False

    def __getPeriod(self, name):
        """Extract a period specification from the configuration"""
        for key, value in self.other_objs:
            if key == name and type(value) == list:
                for v in value:
                    try:
                        period = int(get_attrib(v, 'period'))
                        return period
                    except (AttributeError, ValueError):
                        pass
        return None

    def monitorPeriod(self):
        """Return the monitoring period (None if not specified)"""
        return self.__getPeriod("monitor")

    def watchdogPeriod(self):
        """return the watchdog period (None if not specified)"""
        return self.__getPeriod("watchdog")

    def updateHitSpoolTimes(self):
        """Return the monitoring period (None if not specified)"""
        return not self.__getBoolean("updateHitSpoolTimes", "disabled")

    def configFile(self):
        """added to match the signature of the old code"""
        return self.filename

    def addComponent(self, compName, strict, host=None):
        """Add a component name"""
        pound = compName.rfind("#")
        if pound < 0:
            self.__comps.append(Component(compName, 0, host=host))
        elif strict:
            raise BadComponentName("Found \"#\" in component name \"%s\"" %
                                   compName)
        else:
            self.__comps.append(Component(compName[:pound],
                                          int(compName[pound + 1:]),
                                          host=host))

    def components(self):
        objs = self.__comps[:]
        objs.sort()
        return objs

    def omit(self, hubIdList, keepList=False):
        """
        Create a new run configuration which omits the specified hubs.
        If 'keepList' is True, omit all hubs which are NOT in the list
        """

        omit_dict = {'runConfig': \
                         {'__children__': {},
                          '__attribs__': {}
                          }
                     }

        # these wouldn't be affected by the omit procedure
        # copy the trigger config
        # copy the runComponents
        # copy other objects
        omit_dict['runConfig']['__children__']['triggerConfig'] = \
            self.trig_cfg.initial_dict

        omit_dict['runConfig']['__children__']['runComponent'] = \
            self.run_comps

        for k, v in self.other_objs:
            if k not in omit_dict['runConfig']['__children__']:
                omit_dict['runConfig']['__children__'][k] = []
            omit_dict['runConfig']['__children__'][k].extend(v)

        if self.is_old_runconfig():
            # backwards compatibility support
            for dc in self.dom_cfgs:
                if (keepList and dc.hub_id in hubIdList) or \
                        (not keepList and dc.hub_id not in hubIdList):
                    # copy
                    if 'domConfigList' \
                            not in omit_dict['runConfig']['__children__']:
                        omit_dict['runConfig'][
                            '__children__']['domConfigList'] = []

                    dc_fname = os.path.splitext(os.path.basename(dc.filename))[0]
                    tmp_cfg_list = {'__attribs__': {'hub': '%d' % dc.hub_id},
                                    '__contents__': dc_fname}

                    omit_dict['runConfig'][
                        '__children__']['domConfigList'].append(tmp_cfg_list)

        # stringHub, replayHub can all be affected
        # stringhubs
        for shub in self.stringhub_map.values():
            if shub is None or shub.inferred:
                # inferred hubs are one generated by
                # being referred to in an old runconfig
                continue

            if (keepList and shub.hub_id in hubIdList) or \
                    (not keepList and shub.hub_id not in hubIdList):
                # copy
                if 'stringHub' not in omit_dict['runConfig']['__children__']:
                    omit_dict['runConfig']['__children__']['stringHub'] = []
                omit_dict['runConfig']['__children__']['stringHub'].append(
                    shub.xdict)

        # replay hubs
        # rebin by basedir
        replay_base_dir = {}
        for rhub in self.replay_hubs:
            if (keepList and rhub.hub_id in hubIdList) or \
                    (not keepList and rhub.hub_id not in hubIdList):
                if rhub.base_dir not in replay_base_dir:
                    replay_base_dir[rhub.base_dir] = []
                replay_base_dir[rhub.base_dir].append(rhub)

        for bdir in replay_base_dir:
            if 'hubFiles' not in omit_dict['runConfig']['__children__']:
                omit_dict['runConfig'][
                    '__children__']['hubFiles'][
                    '__children__'].append(
                        {'__children__': replay_base_dir[bdir],
                         '__attribs__': {'baseDir': bdir}
                         }
                        )

        return xml_dict.toString(omit_dict)

    @staticmethod
    def createOmitFileName(config_dir, file_name, hub_id_list, keepList=False):
        """
        Create a new file name from the original name and the list of hubs.
        """
        baseName = os.path.basename(file_name)
        if baseName.endswith(".xml"):
            baseName = baseName[:-4]

        if keepList:
            xstr = "-only"
            join_str = "-"
        else:
            xstr = ""
            join_str = "-no"

        hub_names = [HubIdUtils.get_hub_name(h) for h in hub_id_list]
        join_list = [ "%s%s" % (join_str, hub_name) for hub_name in hub_names ]
        xstr = "%s%s" % (xstr, ''.join(join_list))

        return os.path.join(config_dir, baseName + xstr + ".xml")

    @classmethod
    def find_config(cls, filename):
        """given a dom config filename
        look for it and generate a path"""

        (config_dir, basename) = super(DAQConfig, cls).find_config(filename)

        return os.path.join(config_dir, basename)

    def is_old_runconfig(self):
        """Check to see if the currently loaded runconfig
        is in the old format"""

        # no more domConfigList's allowed
        if 'domConfigList' in self.xdict['runConfig']['__children__']:
            return True

        # each stringHub must have a 'domConfig' attribute
        if 'stringHub' in self.xdict['runConfig']['__children__']:
            hubs = self.xdict['runConfig']['__children__']['stringHub']
            for hub in hubs:
                try:
                    get_attrib(hub, 'domConfig')
                except AttributeError:
                    return True

        # passed all origional tests assume new format
        return False

    @ConfigObject.filename.setter
    def filename(self, filename):
        """check for the filename
        parse it, and check for any exceptions"""

        ConfigObject.filename.__set__(self, filename)

        self.dom_cfgs = []
        self.stringhub_map = {}
        self.replay_hubs = []
        self.other_objs = []
        # contains dash Component objects
        self.__comps = []
        # contains xml dictionary information
        self.run_comps = []
        # check for runConfig tag
        if 'runConfig' not in self.xdict:
            raise DAQConfigException("Missing required <runConfig> tag")

        # cache if this is an old style runconfig or not
        is_old_runconfig = self.is_old_runconfig()

        # unique children of the runConfig tag
        for key, val in self.xdict['runConfig']['__children__'].iteritems():
            if not isinstance(key, str):
                # skip comments
                continue
            elif 'triggerConfig' in key:
                self.trig_cfg = TriggerConfig(val)
            elif 'runComponent' in key:
                #self.runComp = RunComponentList(entry)
                self.run_comps = val
                self.comps = []
                for run_comp in val:
                    name = get_attrib(run_comp, "name")
                    self.addComponent(name, False)
            elif 'domConfigList' in key and is_old_runconfig:
                # required for backwards compatibility
                self.dom_cfgs = []
                for dcfg in val:
                    dom_config_val = get_value(dcfg)
                    dom_config = DomConfig(dom_config_val)
                    self.dom_cfgs.append(dom_config)
            elif 'stringHub' in key:
                for strhub_dict in val:
                    str_hub_id = int(get_attrib(strhub_dict, "hubId"))
                    if str_hub_id not in self.stringhub_map:
                        if not is_old_runconfig:
                            domConfig = get_attrib(strhub_dict, 'domConfig')
                            self.dom_cfgs.append(DomConfig(domConfig))


                        str_hub = StringHub(strhub_dict, str_hub_id)
                        self.stringhub_map[str_hub_id] = str_hub
                        self.addComponent(str_hub.fullName(), False)
            elif 'replayFiles' in key:
                # found a replay hub
                self.replay_hubs = []
                for replay_hub in val:
                    old_style = False
                    try:
                        # get replay attributes
                        base_dir = get_attrib(replay_hub, 'dir')
                    except AttributeError:
                        try:
                            # get old-style replay attributes
                            base_dir = get_attrib(replay_hub, 'baseDir')
                            old_style = True
                        except:
                            # must not be a replay entry
                            print "Ignoring " + str(replay_hub)
                            continue
                    for key in ("data", "hits"):
                        try:
                            for rhub_dict in replay_hub['__children__'][key]:
                                rh_obj = ReplayHub(rhub_dict, base_dir,
                                                   old_style)
                                self.replay_hubs.append(rh_obj)
                                self.addComponent(rh_obj.fullName(), False,
                                                  host=rh_obj.host)
                        except KeyError:
                            # missing keys..
                            pass
            else:
                # an 'OTHER' object
                self.other_objs.append((key, val))

        # previously the config code would create a
        # stringhub object for any hubs defined in a domconfiglist
        # this USED to be the case, but according to dave we
        # can remove this oddity
        # still, check and see if someone is expecting this behavior
        # and if they are raise an exception
        if is_old_runconfig:
            for dom_cfg in self.dom_cfgs:
                hubs = dom_cfg.string_map.keys()
                if len(hubs) > 1:
                    raise DAQConfigException(
                        "Only one string allowed per dom config: %s" \
                            % dom_cfg.filename)
                for hId in hubs:
                    if hId not in self.stringhub_map:
                        strHub = StringHub(None, hId, inferred=True)
                        self.stringhub_map[hId] = strHub
                        self.addComponent(strHub.fullName(), False)

        # if 'STRICT' is specified call the validation
        # routine
        if self.strict:
            self.validate()

    def hasDOM(self, domid):
        """Take a hex string and search for a dom
        with that id.

        If the string is bad throw a BadDomID exception.
        Return true if the dom with the given id is found
        and false otherwise"""
        try:
            val = long(domid, 16)
            domid = val
        except ValueError:
            raise BadDOMID("Invalid DOM ID \"%s\"" % domid)

        for dcfg in self.dom_cfgs:
            for entry in dcfg.rundoms:
                if entry.id() == domid:
                    return True

        return False

    def getAllDOMs(self):
        """Get a list of all doms"""

        dlist = []
        for dcfg in self.dom_cfgs:
            dlist.extend(dcfg.rundoms)
        return dlist

    def getIDbyName(self, name):
        """Search for a dom with the given name
        and return it's id.  If no match is found
        throw a DOMNotInConfigException"""
        for dcfg in self.dom_cfgs:
            for entry in dcfg.rundoms:
                if entry.name() == name:
                    return "%012x" % entry.id()

        raise DOMNotInConfigException("Cannot find dom named \"%s\"" % name)

    def getIDbyStringPos(self, string, pos):
        """Search for the id of a dom at a given string / position
        In case the dom is not found throw a DOMNotInConfigException"""

        for dcfg in self.dom_cfgs:
            try:
                for entry in dcfg.string_map[string]:
                    if entry.pos() == pos:
                        return "%012x" % entry.id()
            except KeyError:
                # ignore KeyError exceptions looking for our given string
                pass

        raise DOMNotInConfigException("Cannot find sting %d pos %d" %
                                      (string, pos))

    def getDomConfigs(self):
        return self.dom_cfgs

    def getTriggerConfig(self):
        return self.trig_cfg


class DAQConfigParser(object):
    def __init__(self):
        """Utility class, do not instantiate"""
        raise TypeError("Cannot create this object")

    @classmethod
    def load(cls, file_name, configDir=None, strict=False):
        if not configDir is None:
            FindConfigDir.CONFIG_DIR = configDir

        return DAQConfig(file_name, strict)

    @classmethod
    def parse(cls, config_dir, file_name, strict=False):
        if not config_dir is None:
            FindConfigDir.CONFIG_DIR = config_dir
        return DAQConfig(file_name, strict)

    @classmethod
    def getClusterConfiguration(cls, configName, useActiveConfig=False,
                                clusterDesc=None, configDir=None, strict=False,
                                validate=True):
        """
        Find and parse the cluster configuration
        """

        if configName is None:
            configName = \
                CachedConfigName.getConfigToUse(None, False, useActiveConfig)
            if configName is None:
                raise ConfigNotSpecifiedException("No configuration specified")

        sep_index = configName.find('@')
        if sep_index > 0:
            clusterDesc = configName[sep_index + 1:]
            configName = configName[:sep_index]

        if configDir is None:
            configDir = find_pdaq_config()

        if validate:
            (valid, reason) = validate_configs(clusterDesc, configName)

            if not valid:
                raise DAQConfigException(reason)

        # load the run configuration
        runCfg = DAQConfigParser.parse(configDir, configName, strict=strict)

        return RunCluster(runCfg, clusterDesc, configDir)


def main():
    import argparse
    import datetime
    from exc_string import exc_string

    parse = argparse.ArgumentParser()
    parse.add_argument("-c", "--check-config", dest="toCheck",
                     help="Check whether configuration is valid")
    parse.add_argument("-S", "--not-strict", dest="strict",
                     action="store_false", default=True,
                     help="Do not perform strict checking")
    parse.add_argument("-m", "--no-host-check", dest="nohostcheck",
                     default=False,
                     help="Disable checking the host type for run permission")
    parse.add_argument("-q", "--quiet", dest="quiet",
                     action="store_true", default=False,
                     help="Don't print anything if config is OK")
    parse.add_argument("-x", "--extended-tests", dest="extended",
                     action="store_true", default=False,
                     help="Do extended testing")
    parse.add_argument("-z", "--no-schema-validation", dest="validation",
                     action="store_false", default=True,
                     help=("Disable schema validation of xml "
                           "configuration files"))
    parse.add_argument("xmlfile", nargs="*")
    args = parse.parse_args()

    if not args.nohostcheck:
        hostid = Machineid()
        if (not (hostid.is_build_host() or hostid.is_control_host() or
                 (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
            # to run daq launch you should either be a control host or
            # a totally unknown host
            print >> sys.stderr, ("Are you sure you are running DAQConfig "
                                  "on the correct host?")
            raise SystemExit

    config_dir = find_pdaq_config()

    if args.toCheck:
        try:
            DAQConfigParser.load(args.toCheck, config_dir, args.strict)
            if args.validation:
                (valid, reason) = validate_configs(None, args.toCheck)

                if not valid:
                    raise DAQConfigException(reason)

            if not args.quiet:
                print "%s/%s is ok." % (config_dir, args.toCheck)
                status = None
        except DAQConfigException as config_except:
            raise SystemExit(config_except)
        except:
            status = "%s/%s is not a valid config: %s" % \
                (config_dir, args.toCheck, exc_string())
            raise SystemExit(status)

    # Code for testing:
    #if len(args.xmlfile) == 0:
    #    args.xmlfile.append("sim5str")

    for config_name in args.xmlfile:
        if args.extended and not args.quiet:
            print '-----------------------------------------------------------'
            print "Config %s" % config_name
        start_time = datetime.datetime.now()
        try:
            dc = DAQConfigParser.load(config_name, config_dir, args.strict)
        except Exception:
            print 'Could not parse "%s": %s' % (config_name, exc_string())
            continue

        if args.validation:
            (valid, reason) = validate_configs(None, config_name)
            if not valid:
                raise DAQConfigException(reason)

        if not args.extended:
            if not args.quiet:
                print "%s is ok" % config_name
        else:
            diff = datetime.datetime.now() - start_time
            init_time = float(diff.seconds) + \
                (float(diff.microseconds) / 1000000.0)
            comps = dc.components()
            if not args.quiet:
                comps.sort()
                for comp in comps:
                    print 'Comp %s log %s' % (str(comp), str(comp.logLevel()))

            start_time = datetime.datetime.now()
            dc = DAQConfigParser.load(config_name, config_dir, args.strict)
            diff = datetime.datetime.now() - start_time
            next_time = float(diff.seconds) + \
                (float(diff.microseconds) / 1000000.0)
            if not args.quiet:
                print "Initial time %.03f, subsequent time: %.03f" % \
                    (init_time, next_time)


if __name__ == "__main__":
    main()
