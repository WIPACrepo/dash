from lxml import etree
from lxml.etree import XMLSyntaxError
import os, sys

try:
    from CachedConfigName import CachedConfigName
except ImportError:
    sys.path.append('..')
    from CachedConfigName import CachedConfigName

from ClusterDescription import ClusterDescription

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if "PDAQ_HOME" in os.environ:
    META_DIR = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    META_DIR = find_pdaq_trunk()




def validate_configs(cluster_xml_filename, runconfig_xml_filename,
                     default_dom_geom_xml_filename = None):

    # ---------------------------------------------------------
    # build up a path and validate the default_dom_geometry file
    dom_geom_xml_path = os.path.join(META_DIR, "config", "default-dom-geometry.xml")
    (valid, reason) = validate_default_dom_geom(dom_geom_xml_path)
    if not valid:
        return (valid, reason)


    # -------------------------------------------------
    # validate the cluster config
    # really odd file name rules..  but try to keep it consistent
    if cluster_xml_filename==None:
        cluster_xml_filename = ClusterDescription.getClusterFromHostName()

    if cluster_xml_filename.endswith('.xml'):
        # old cluster configs not supported
        return (False, "Old style cluster configs not supported '%s'" % cluster_xml_filename)

    cluster_xml_filename = os.path.basename(cluster_xml_filename)
    fname, extension = os.path.splitext(cluster_xml_filename)
    if not fname.endswith('-cluster'):
        fname = "%s-cluster" % fname

    if not extension or extension is not 'cfg':
        extension = 'cfg'

    cluster_xml_filename = "%s.%s" % ( fname, extension)

    cluster_xml_filename = os.path.join(META_DIR, 'config', 
                                        os.path.basename(cluster_xml_filename))

    (valid, reason ) = validate_clusterconfig(cluster_xml_filename)
    if not valid:
        return (valid, reason)

    # validate the run configuration
    # assume an .xml extension for the run config and add if required
    
    # RUN configs are cached, not cluster
    if runconfig_xml_filename is None:
        runconfig_xml_filename = CachedConfigName.getConfigToUse(
            runconfig_xml_filename, False, True)
    
    # oddly enough some code skips passing in a run config sometimes
    # just passing in the cluster configuration instead.  so 
    # be okay with no run config
    if runconfig_xml_filename is None:
            return (True, "")

    if not runconfig_xml_filename.endswith('.xml'):
        runconfig_xml_filename = "%s.xml" % runconfig_xml_filename

    runconfig_xml_filename = os.path.join(META_DIR, 'config',
                                          os.path.basename(runconfig_xml_filename))
    (valid, reason) = validate_runconfig(runconfig_xml_filename)
    if not valid:
        return (valid, reason)


    # parse the run config for all domConfigList, and trigger
    try:
        with open(runconfig_xml_filename, 'r') as xml_fd:
            try:
                doc_xml = etree.parse(xml_fd)
            except XMLSyntaxError, e:
                return (False, "file: '%s', %s" % ( runconfig_xml_filename, e))
    except IOError:
        # cannot open the run config file
        return (False, "Cannot open runconfig '%s'" % runconfig_xml_filename)
        
    run_configs = doc_xml.getroot()

    dconfigList = run_configs.findall('domConfigList')
    for dconfig in dconfigList:
        dom_config_txt = "%s.xml" % dconfig.text
        dom_config_path = os.path.join(META_DIR, 'config', 'domconfigs',
                                       dom_config_txt)

        (valid, reason) = validate_dom_config_sps(dom_config_path)

        if not valid:
            return (False, reason)

    trigConfigList = run_configs.findall('triggerConfig')
    for trigConfig in trigConfigList:
        trig_config_txt = "%s.xml" % trigConfig.text
        trig_config_path = os.path.join(META_DIR, 'config', 'trigger',
                                        trig_config_txt)

        (valid, reason) = validate_trigger(trig_config_path)
        if not valid:
            return (False, reason)

    return (True, "")


def validate_clusterconfig(xml_filename):
    """Check the cluster config files against an xml schema"""
    (valid, reason) = _validate_xml(xml_filename, 'clustercfg.xsd')

    return ( valid, reason )

def validate_runconfig(xml_filename):
    """Check the runconfig against an xml schema"""
    (valid, reason) = _validate_xml_rng(xml_filename, 'runconfig.rng')

    return ( valid, reason )

def validate_default_dom_geom(xml_filename):
    """Check the default dom geometry against the xml schema"""
    (valid, reason) = _validate_xml(xml_filename, 'geom.xsd')

    return ( valid, reason )

def validate_trigger(xml_filename):
    """Check the trigger config against the xml schema"""
    (valid, reason) = _validate_xml(xml_filename, 'trigger.xsd')

    return ( valid, reason )


def validate_dom_config_sps(xml_filename):
    """Check a dom config file against the appropriate xml schema"""
    (valid, reason) = _validate_dom_config_xml(xml_filename, 'domconfig-sps.xsd',
                                               'domconfig-sim.xsd')

    return (valid, reason)

def validate_dom_config_spts(xml_filename):
    """Check a dom config file against the appropriate xml schema"""
    (valid, reason) = _validate_dom_config_xml(xml_filename, 'domconfig-spts.xsd',
                                               'domconfig-sim.xsd')

    return (valid, reason)



def _validate_dom_config_xml(xml_filename, xsd_real_filename, xsd_sim_filename):
    """
    This method will look a bit hack'ish.  
    The dom configs for the real doms is a bit problematic as the elements
    can occur in any order ( probably due to hand editing the files )  This 
    means we have to use xsd:all ( or list all possible orders of arguments -
    which will be large due to the number of possible elements ).  You cannot
    use an xsd:all inside a choice as that makes the resulting grammar 
    non-determinisitc.  

    So we get around this problem by reading the document in an unvalidated 
    fashion, look for a simulation tag, and then validate the xml file 
    depending on that tag.  Any simplifications I could come up with would
    require altering the format for the dom config files, or editing all
    configs neither of which is desirable.
    """

    try:
        with open(xml_filename, 'r') as xml_fd:
            try:
                doc_xml = etree.parse(xml_fd)
            except XMLSyntaxError, e:
                return (False, "file: '%s', %s" % (xml_filename, e))
    except IOError, e:
        return (False, "Cannot open: %s" % xml_filename)
        
    found_simulation = False
    
    dom_configs = doc_xml.findall('domConfig')
    for dconfig in dom_configs:
        simulation = dconfig.findall('simulation')
        if len(simulation)!=0:
            found_simulation = True

    # now we know the type of the file
    if found_simulation:
        xsd_sim_fd = None
        try:
            try:
                xsd_sim_fd = open(xsd_sim_filename, 'r')
            except IOError:
                xsd_sim_path = os.path.join(META_DIR,"config", 
                                            "xsd", 
                                            os.path.basename(xsd_sim_filename))

                xsd_sim_fd = open(xsd_sim_path, 'r')
            xmlschema_doc = etree.parse(xsd_sim_fd)
        finally:
            if xsd_sim_fd is not None:
                xsd_sim_fd.close()
            
        xsd_sim = etree.XMLSchema(xmlschema_doc)
        if xsd_sim.validate(doc_xml):
            return (True, "")
        else:
            return (False, "%s" % xsd_sim.error_log)
    else:
        xsd_real_fd = None
        try:
            try:
                xsd_real_fd = open(xsd_real_filename, 'r')
            except IOError:
                xsd_real_path = os.path.join(META_DIR, "config",
                                           "xsd", 
                                           os.path.basename(xsd_real_filename))

                xsd_real_fd = open(xsd_real_path, 'r')

            xmlschema_doc = etree.parse(xsd_real_fd)
        finally:
            if xsd_real_fd is not None:
                xsd_real_fd.close()

        xsd_real = etree.XMLSchema(xmlschema_doc)

        if xsd_real.validate(doc_xml):
            return (True, "")
        else:
            return (False, "%s" % xsd_real.error_log)

def _validate_xml_rng(xml_filename, relaxng_filename):
    """Arguments:
    xml_filename: path to an xml file
    rng_filename: path to an rng file used to validate the xml file

    Returns: ( a tuple ) - 
    (valid, reason) ->
        valid - is true if the xml file is validated by the schema and false otherwise
        reason - text describing why the xml file is invalid if it is invalid
    """

    try:
        try:
            relaxng_fd = open(relaxng_filename, 'r')
        except IOError:
            # look in the config/xsd directory
            relaxng_path = os.path.join(META_DIR, 'config', 
                                        'xsd', 
                                        os.path.basename(relaxng_filename))

            try:
                relaxng_fd = open(relaxng_path, 'r')
            except IOError:
                return (False, "could not rng open: '%s'" % relaxng_path)

        relaxng_doc = etree.parse(relaxng_fd)
    finally:
        if relaxng_fd is not None:
            relaxng_fd.close()

    relaxng = etree.RelaxNG(relaxng_doc)

    try:
        with open(xml_filename, 'r') as doc_fd:
            try:
                doc_xml = etree.parse(doc_fd)
            except XMLSyntaxError, e:
                return (False, "file: '%s' %s" % (xml_filename, e))
    except IOError:
        return (False, "Could not open '%s'" % xml_filename)

    if relaxng.validate(doc_xml):
        return (True, "")
    else:
        return (False, "%s" % relaxng.error_log)



def _validate_xml(xml_filename, xsd_filename):
    """Arguments:
    xml_filename: path to an xml file
    xsd_filename: path to an xsd file used to validate the xml file

    Returns: ( a tuple ) - 
    (valid, reason) ->
        valid - is true if the xml file is validated by the schema and false otherwise
        reason - text describing why the xml file is invalid if it is invalid
    """

    # real dom config xsd
    xsd_fd = None
    try:
        try:
            xsd_fd = open(xsd_filename, 'r')
        except IOError:
            # look in the config/xsd directory
            xsd_path = os.path.join(META_DIR, 'config', 
                                    'xsd', 
                                    os.path.basename(xsd_filename))

            try:
                xsd_fd = open(xsd_path, 'r')
            except IOError:
                return (False, "could not xsd open: '%s'" % xsd_path)

        xmlschema_doc = etree.parse(xsd_fd)
    finally:
        if xsd_fd is not None:
            xsd_fd.close()

    xsd = etree.XMLSchema(xmlschema_doc)

    try:
        with open(xml_filename, 'r') as doc_fd:
            try:
                doc_xml = etree.parse(doc_fd)
            except XMLSyntaxError, e:
                return (False, "file: '%s' %s" % (xml_filename, e))
    except IOError:
        return (False, "Could not open '%s'" % xml_filename)

    if xsd.validate(doc_xml):
        return (True, "")
    else:
        return (False, "%s" % xsd.error_log)

    

if __name__=="__main__":
    print "validate_configs"
    (valid, reason) = validate_configs('../../config/localhost-cluster.cfg',
                                       '../../config/sim60str-25Hz.xml')

    if not valid:
        print "Configuration invalid ( reasons: )"
        print reason
    else:
        print "Configuration is valid"

