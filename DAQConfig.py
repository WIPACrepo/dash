import os
import sys
from xml_dict import xml_dict
from xml_dict import get_value
from xml_dict import get_attrib

from DefaultDomGeometry import BadFileError, DefaultDomGeometryReader, \
    ProcessError
from locate_pdaq import find_pdaq_config

from utils.Machineid import Machineid
from xsd.validate_configs import validate_configs
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
    def __init__(self, xdict, hub_id):
        self.xdict = xdict
        self.hub_id = int(hub_id)
        super(StringHub, self).__init__("stringHub", hub_id)

    def isDeepCore(self):
        return HubIdUtils.is_deep_core(self.__id)

    def isIceTop(self):
        return HubIdUtils.is_icetop(self.__id)

    def isInIce(self):
        return HubIdUtils.is_in_ice(self.__id)


class ReplayHub(Component):
    "Replay hub data from a run configuration file"

    def __init__(self, xdict, base_dir):
        self.base_dir = base_dir
        self.xdict = xdict
        self.hitFile = get_attrib(xdict, 'hitFile')
        hub_id = int(get_attrib(xdict, 'id'))

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
    exposed from the old code where for setting state from
    parsing code.  Setting values from parsing code is no
    longer needed"""

    DEFAULT_DOM_GEOMETRY = None

    def __init__(self, dom_dict):
        self.dom_dict = dom_dict

        self.__id = long(self['mbid'], 16)
        self.__name = self['name']

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

        try:
            dom_configs = \
                self.xdict['domConfigList']['__children__']['domConfig']

            for entry in dom_configs:
                rd = RunDom(entry)
                self.rundoms.append(rd)

                string = rd.string()
                if string not in self.string_map:
                    self.string_map[string] = []
                self.string_map[string].append(rd)

        except KeyError:
            raise AttributeError("File: %s not valid" % filename)


class DomConfigList(object):
    def __init__(self, domcfg_list):
        self.xdict = domcfg_list

        self.comps = []
        self.other_objs = []
        self.run_comps = []
        self.stringhub_map = {}
        self.replay_hubs = {}

        try:
            self.hub_id = get_attrib(domcfg_list, 'hub')
            self.hub_id = int(self.hub_id)
        except ValueError:
            # bad hub_id attribute
            raise AttributeError("Bad hub id attribute: %s" % self.hub_id)
        except AttributeError:
            # couldn't find a hub attribute..  doesn't matter
            self.hub_id = None

        self.basename = get_value(domcfg_list)

        self.dom_config = DomConfig(self.basename)
        self.replay_hubs = []

    def getAllDOMs(self):
        return self.dom_config.rundoms

    def contains_hub(self, hub_id):
        return hub_id in self.dom_config.string_map

    def getDOMById(self, domid):
        """get a dom object by the motherboard id"""
        for entry in self.dom_config.rundoms:
            if entry.id() == domid:
                return entry
        return None

    def getDOMByName(self, name):
        """get a dom by it's name"""
        for entry in self.dom_config.rundoms:
            if entry.name() == name:
                return entry
        return None

    def getDOMByStringPos(self, string, pos):
        """get the dom on a given string and position"""
        try:
            for entry in self.dom_config.string_map[string]:
                if entry.pos() == pos:
                    return entry
        except KeyError:
            pass
        return None

    def getDOMsByHub(self, hub):
        """get the dom by a hub id"""

        if hub in self.dom_config.string_map:
            if len(self.dom_config.string_map[hub]) == 0:
                return None
            else:
                return self.dom_config.string_map[hub]
        return []

    def hubs(self):
        """Get a list of hubs referenced in this config"""
        return self.dom_config.string_map.keys()


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

        if len(self.stringhub_map)==0:
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
            if fname.endswith(".xml") and cfg!='default-dom-geometry':
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

                

    def configFile(self):
        """added to match the signature of the old code"""
        return self.filename

    def addComponent(self, compName, strict):
        """Add a component name"""
        pound = compName.rfind("#")
        if pound < 0:
            self.__comps.append(Component(compName, 0))
        elif strict:
            raise BadComponentName("Found \"#\" in component name \"%s\"" %
                                   compName)
        else:
            self.__comps.append(Component(compName[:pound],
                                          int(compName[pound + 1:])))

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
            omit_dict['runConfig']['__children__'][k].append(v)

        # domConfigList, stringHub, replayHub can all be affected
        for dc in self.dom_cfgs:
            if (keepList and dc.hub_id in hubIdList) or \
                    (not keepList and dc.hub_id not in hubIdList):
                # copy
                if 'domConfigList' \
                        not in omit_dict['runConfig']['__children__']:
                    omit_dict['runConfig'][
                        '__children__']['domConfigList'] = []
                omit_dict['runConfig']['__children__']['domConfigList'].append(
                    dc.xdict)

        # stringhubs
        for shub in self.stringhub_map.items():
            if shub is None:
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

        print xml_dict.toString(omit_dict)

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
        xstr = "%s%s" % (xstr, join_str.join(hub_names))

        return os.path.join(config_dir, baseName + xstr + ".xml")

    @classmethod
    def find_config(cls, filename):
        """given a dom config filename
        look for it and generate a path"""

        (config_dir, basename) = super(DAQConfig, cls).find_config(filename)

        return os.path.join(config_dir, basename)

    @ConfigObject.filename.setter
    def filename(self, filename):
        """check for the filename
        parse it, and check for any exceptions"""

        ConfigObject.filename.__set__(self, filename)

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
            elif 'domConfigList' in key:
                # there may be more than one dom config list
                self.dom_cfgs = []
                for dcfg_list in val:
                    domcfg_list = DomConfigList(dcfg_list)
                    self.dom_cfgs.append(domcfg_list)
            elif 'stringHub' in key:
                # found a stringhub
                for strhub_dict in val:
                    str_hub_id = int(get_attrib(strhub_dict, "hubId"))
                    if str_hub_id not in self.stringhub_map:
                        str_hub = StringHub(strhub_dict, str_hub_id)
                        self.stringhub_map[str_hub_id] = str_hub
                        self.addComponent(str_hub.fullName(), False)
            elif 'hubFiles' in key:
                # found a replay hub
                self.replay_hubs = []
                for replay_hub in val:
                    try:
                        base_dir = get_attrib(replay_hub, 'baseDir')
                        for rhub_dict in replay_hub['__children__']['hub']:
                            rh_obj = ReplayHub(rhub_dict, base_dir)
                            self.replay_hubs.append(rh_obj)
                            self.addComponent(rh_obj.fullName(), False)
                    except KeyError:
                        # missing keys..
                        pass
            else:
                # an 'OTHER' object
                self.other_objs.append((key, val))

        # the configuration file is a bit odd, it
        # assumes stringhubs for any not directly
        # specified
        for dcfg_list in self.dom_cfgs:
            hubs = dcfg_list.hubs()
            for hId in hubs:
                if hId not in self.stringhub_map:
                    strHub = StringHub(None, hId)
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
            dom = dcfg.getDOMById(domid)
            if dom is not None:
                return True

        return False

    def getAllDOMs(self):
        """Get a list of all doms"""

        dlist = []
        for dcfg in self.dom_cfgs:
            dlist.extend(dcfg.getAllDOMs())
        return dlist

    def getIDbyName(self, name):
        """Search for a dom with the given name
        and return it's id.  If no match is found 
        throw a DOMNotInConfigException"""
        for dcfg in self.dom_cfgs:
            dom = dcfg.getDOMByName(name)
            if dom is not None:
                return "%012x" % dom.id()

        raise DOMNotInConfigException("Cannot find dom named \"%s\"" % name)

    def getIDbyStringPos(self, string, pos):
        """Search for the id of a dom at a given string / position
        In case the dom is not found throw a DOMNotInConfigException"""
        for dcfg in self.dom_cfgs:
            dom = dcfg.getDOMByStringPos(string, pos)
            if dom is not None:
                return "%012x" % dom.id()

        raise DOMNotInConfigException("Cannot find sting %d pos %d" %
                                      (string, pos))

    def getDomConfigNames(self):
        flist = []
        for dcfg in self.dom_cfgs:
            flist.append(dcfg.basename)

        return flist

    def getTriggerConfigName(self):
        name = None
        if self.trig_cfg:
            name = self.trig_cfg.filename
        return name


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
        Find and parse the cluster configuration from either the run
        configuration dir
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
        runCfg = DAQConfigParser.parse(configDir, configName, strict=False)

        return RunCluster(runCfg, clusterDesc, configDir)


def main():
    parse = optparse.OptionParser()
    parse.add_option("-c", "--check-config", type="string", dest="toCheck",
                     action="store", default=None,
                     help="Check whether configuration is valid")
    parse.add_option("-S", "--not-strict", dest="strict",
                     action="store_false", default=True,
                     help="Do not perform strict checking")
    parse.add_option("-m", "--no-host-check", dest="nohostcheck", default=False,
                     help="Disable checking the host type for run permission")
    parse.add_option("-q", "--quiet", dest="quiet",
                     action="store_true", default=False,
                     help="Don't print anything if config is OK")
    parse.add_option("-x", "--extended-tests", dest="extended",
                     action="store_true", default=False,
                     help="Do extended testing")
    parse.add_option("-z", "--no-schema-validation", dest="validation",
                     action="store_false", default=True,
                     help=("Disable schema validation of xml "
                           "configuration files"))
    opt, args = parse.parse_args()
        
    if not opt.nohostcheck:
        hostid = Machineid()
        if (not (hostid.is_build_host() or
                 (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
            # to run daq launch you should either be a control host or
            # a totally unknown host
            print >> sys.stderr, ("Are you sure you are running DAQConfig "
                                  "on the correct host?")
            raise SystemExit
            
    config_dir = find_pdaq_config()
            
    if opt.toCheck:
        try:
            DAQConfigParser.load(opt.toCheck, config_dir, opt.strict)
            if opt.validation:
                (valid, reason) = validate_configs(None, opt.toCheck)
                
                if not valid:
                    raise DAQConfigException(reason)
                
            if not opt.quiet:
                print "%s/%s is ok." % (config_dir, opt.toCheck)
                status = None
        except:
            status = "%s/%s is not a valid config: %s" % \
                (config_dir, opt.toCheck, exc_string())
            raise SystemExit(status)

    # Code for testing:

    if len(args) == 0:
        args.append("sim5str")

    for config_name in args:
        if opt.extended:
            print '-----------------------------------------------------------'
            print "Config %s" % config_name
        start_time = datetime.datetime.now()
        try:
            dc = DAQConfigParser.load(config_name, config_dir, opt.strict)
            print "DC.comps: ", dc.components()
        except Exception:
            print 'Could not parse "%s": %s' % (config_name, exc_string())
            continue
        
        if opt.validation:
            (valid, reason) = validate_configs(None, config_name)
            if not valid:
                raise DAQConfigException(reason)

        if not opt.extended:
            if not opt.quiet:
                print "%s is ok" % config_name
        else:
            diff = datetime.datetime.now() - start_time
            init_time = float(diff.seconds) + \
                (float(diff.microseconds) / 1000000.0)
            comps = dc.components()
            comps.sort()
            for comp in comps:
                print 'Comp %s log %s' % (str(comp), str(comp.logLevel()))

            start_time = datetime.datetime.now()
            dc = DAQConfigParser.load(config_name, config_dir, opt.strict)
            diff = datetime.datetime.now() - start_time
            next_time = float(diff.seconds) + \
                (float(diff.microseconds) / 1000000.0)
            print "Initial time %.03f, subsequent time: %.03f" % \
                (init_time, next_time)


                
if __name__ == "__main__":
    import datetime
    import optparse
    from exc_string import exc_string

    main()
