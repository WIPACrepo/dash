from lxml import etree
from lxml.etree import XMLSyntaxError
import os
import sys
import glob

try:
    from CachedConfigName import CachedConfigName
except ImportError:
    sys.path.append('..')
    from CachedConfigName import CachedConfigName

try:
    from locate_pdaq import find_pdaq_config, find_pdaq_trunk
except ImportError:
    sys.path.append('..')
    from locate_pdaq import find_pdaq_config, find_pdaq_trunk

from ClusterDescription import ClusterDescription


META_DIR = find_pdaq_trunk()
CONFIG_DIR = find_pdaq_config()


def _open_schema(path, description):
    try:
        return open(path, 'r')
    except IOError:
        # look in the schema directory
        path2 = os.path.join(META_DIR, 'schema', os.path.basename(path))

        try:
            return open(path2, 'r')
        except IOError:
            # transitional code between Ale_Asylum and Capital
            # After pDAQ:Brewery:Furthermore has been release, this can go away
            path3 = os.path.join(CONFIG_DIR, 'xsd', os.path.basename(path))

            try:
                return open(path3, 'r')
            except IOError:
                raise IOError("Could not open %s '%s'" % (description, path))


def validate_configs(cluster_xml_filename, runconfig_xml_filename,
                     default_dom_geom_xml_filename=None):

    # ---------------------------------------------------------
    # build up a path and validate the default_dom_geometry file
    dom_geom_xml_path = os.path.join(CONFIG_DIR,
                                     "default-dom-geometry.xml")
    (valid, reason) = validate_default_dom_geom(dom_geom_xml_path)
    if not valid:
        return (valid, reason)

    # -------------------------------------------------
    # validate the cluster config
    # really odd file name rules..  but try to keep it consistent
    if cluster_xml_filename == None:
        cluster_xml_filename = ClusterDescription.getClusterFromHostName()

    if cluster_xml_filename.endswith('.xml'):
        # old cluster configs not supported
        return (False,
                "Old style cluster configs not supported '%s'" % \
                    cluster_xml_filename)

    cluster_xml_filename = os.path.basename(cluster_xml_filename)
    fname, extension = os.path.splitext(cluster_xml_filename)
    if not fname.endswith('-cluster'):
        fname = "%s-cluster" % fname

    if not extension or extension is not 'cfg':
        extension = 'cfg'

    cluster_xml_filename = "%s.%s" % (fname, extension)

    cluster_xml_filename = os.path.join(CONFIG_DIR,
                                        os.path.basename(cluster_xml_filename))

    (valid, reason) = validate_clusterconfig(cluster_xml_filename)
    if not valid:
        return (valid, reason)

    #
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

    runconfig_basename = os.path.basename(runconfig_xml_filename)
    runconfig_xml_filename = os.path.join(CONFIG_DIR,
                                          runconfig_basename)

    (valid, reason) = validate_runconfig(runconfig_xml_filename)
    if not valid:
        return (valid, reason)

    # parse the run config for all domConfigList, and trigger
    try:
        with open(runconfig_xml_filename, 'r') as xml_fd:
            try:
                doc_xml = etree.parse(xml_fd)
            except XMLSyntaxError as e:
                return (False, "file: '%s', %s" % (runconfig_xml_filename, e))
    except IOError:
        # cannot open the run config file
        return (False, "Cannot open runconfig '%s'" % runconfig_xml_filename)

    is_sps = True
    if cluster_xml_filename is not None:
        if not is_sps_cluster(cluster_xml_filename):
            is_sps = False

    run_configs = doc_xml.getroot()

    dconfigList = run_configs.findall('domConfigList')
    for dconfig in dconfigList:
        dom_config_txt = "%s.xml" % dconfig.text
        dom_config_path = os.path.join(CONFIG_DIR, 'domconfigs',
                                       dom_config_txt)

        if is_sps:
            (valid, reason) = validate_dom_config_sps(dom_config_path)
        else:
            (valid, reason) = validate_dom_config_spts(dom_config_path)

        if not valid:
            return (False, reason)

    trigConfigList = run_configs.findall('triggerConfig')
    for trigConfig in trigConfigList:
        trig_config_txt = "%s.xml" % trigConfig.text
        trig_config_path = os.path.join(CONFIG_DIR, 'trigger',
                                        trig_config_txt)

        (valid, reason) = validate_trigger(trig_config_path)
        if not valid:
            return (False, reason)

    return (True, "")


def validate_clusterconfig(xml_filename):
    """Check the cluster config files against an xml schema"""
    (valid, reason) = _validate_xml(xml_filename, 'clustercfg.xsd')

    return (valid, reason)


def validate_runconfig(xml_filename):
    """Check the runconfig against an xml schema"""
    (valid, reason) = _validate_xml_rng(xml_filename, 'runconfig.rng')

    # add a check here to see if this runconfig is in the old format
    if not valid:
        # check the old format
        (old_valid, old_reason) = _validate_xml_rng(xml_filename,
                                                    "runconfig-old.rng")
        if old_valid:
            return (old_valid, old_reason)
        
    return (valid, reason)


def validate_default_dom_geom(xml_filename):
    """Check the default dom geometry against the xml schema"""
    (valid, reason) = _validate_xml(xml_filename, 'geom.xsd')

    return (valid, reason)


def validate_trigger(xml_filename):
    """Check the trigger config against the xml schema"""
    (valid, reason) = _validate_xml(xml_filename, 'trigger.xsd')

    return (valid, reason)


def is_sps_cluster(cluster_xml_filename):
    """sps by definition is the most strict validation
    if we cannot determine the cluster for some reason assume sps"""

    (valid, reason) = validate_clusterconfig(cluster_xml_filename)
    if not valid:
        return True

    try:
        with open(cluster_xml_filename, 'r') as xml_fd:
            try:
                doc_xml = etree.parse(xml_fd)
            except XMLSyntaxError as e:
                return True
    except IOError:
        return True

    # the cluster attribute is the root element of the cluster
    # config xml file
    cluster = doc_xml.getroot()
    if cluster == None:
        return True
    # 'name' is required by the validate_clustercfg code
    # but be a bit paranoid so check for it
    if 'name' not in cluster.attrib:
        return True

    name = cluster.attrib['name']

    # make the localhost cluster be
    # equivalent to the sps cluster
    # This is okay as sps is the most
    # strict cluster
    if name == 'sps':
        return True
    else:
        return False


def validate_dom_config_sps(xml_filename):
    """Check a dom config file against the appropriate xml schema"""
    (valid, reason) = _validate_dom_config_xml(xml_filename,
                                               'domconfig-sps.rng')

    return (valid, reason)


def validate_dom_config_spts(xml_filename):
    """Check a dom config file against the appropriate xml schema"""

    (valid, reason) = _validate_dom_config_xml(xml_filename,
                                               'domconfig-spts.rng')

    return (valid, reason)


def _validate_dom_config_xml(xml_filename, rng_real_filename):

    try:
        with open(xml_filename, 'r') as xml_fd:
            try:
                doc_xml = etree.parse(xml_fd)
            except XMLSyntaxError as e:
                return (False, "file: '%s', %s" % (xml_filename, e))
    except IOError:
        return (False, "Cannot open: %s" % xml_filename)

    with _open_schema(rng_real_filename, "RelaxNG file") as rng_real_fd:
        rng_doc = etree.parse(rng_real_fd)

    rng_real = etree.RelaxNG(rng_doc)

    if rng_real.validate(doc_xml):
        return (True, "")
    else:
        return (False, "%s" % rng_real.error_log)


def _validate_xml_rng(xml_filename, relaxng_filename):
    """Arguments:
    xml_filename: path to an xml file
    rng_filename: path to an rng file used to validate the xml file

    Returns: ( a tuple ) -
    (valid, reason) ->
        valid - is true if the xml file is validated by the schema and
        false otherwise

        reason - text describing why the xml file is invalid if it is
        invalid
    """

    try:
        with _open_schema(relaxng_filename, "RNG schema") as relaxng_fd:
            relaxng_doc = etree.parse(relaxng_fd)
    except IOError as e:
        return (False, str(e))

    relaxng = etree.RelaxNG(relaxng_doc)

    try:
        with open(xml_filename, 'r') as doc_fd:
            try:
                doc_xml = etree.parse(doc_fd)
            except XMLSyntaxError as e:
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
        valid - is true if the xml file is validated by the schema
        and false otherwise

        reason - text describing why the xml file is invalid if it
        is invalid
    """

    # real dom config xsd
    try:
        with _open_schema(xsd_filename, "XSD schema") as xsd_fd:
            xmlschema_doc = etree.parse(xsd_fd)
    except IOError as e:
        return (False, str(e))

    xsd = etree.XMLSchema(xmlschema_doc)

    try:
        with open(xml_filename, 'r') as doc_fd:
            try:
                doc_xml = etree.parse(doc_fd)
            except XMLSyntaxError as e:
                return (False, "file: '%s' %s" % (xml_filename, e))
    except IOError:
        return (False, "Could not open '%s'" % xml_filename)

    if xsd.validate(doc_xml):
        return (True, "")
    else:
        return (False, "%s" % xsd.error_log)


if __name__ == "__main__":

    print "-" * 60
    print "Validating all sps configurations"
    print "-" * 60
    sps_configs = glob.glob(os.path.join(CONFIG_DIR, 'sps*.xml'))

    print "validate_configs"
    print "Validating all sps configurations"
    for config in sps_configs:
        print ""
        print "Validating %s" % config
        (valid, reason) = validate_configs(os.path.join(CONFIG_DIR,
                                                        'sps-cluster.cfg'),
                                           config)

        if not valid:
            print "Configuration invalid ( reasons: )"
            print reason
        else:
            print "Configuration is valid"


    spts_configs = glob.glob(os.path.join(CONFIG_DIR, 'spts*.xml'))
    print "Validating all sps configurations"
    for config in spts_configs:
        print ""
        print "Validating %s" % config
        (valid, reason) = validate_configs(os.path.join(CONFIG_DIR,
                                                        'spts-cluster.cfg'),
                                           config)

        if not valid:
            print "Configuration invalid ( reasons: )"
            print reason
        else:
            print "Configuration is valid"

