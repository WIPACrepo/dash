import operator
import sys
from  locate_pdaq import find_pdaq_config
from xml_dict import xml_dict
from xml_dict import get_attrib
from xml_dict import set_attrib
from lxml import etree
from lxml.etree import Comment
from DefaultDomGeometry import DefaultDomGeometryReader

import copy
import os
import re


class ConverterException(Exception):
    """Raise this exception on any error in converting a
    run config file to the new format"""
    pass


def domconfig_gethubid(dcfg,
                       domgeom,
                       domconfig_path):
    """Take a domConfigList element - dcfg
    Parse the domconfig file, match with the geometry data to make sure
    all doms in the config are on the same string.  Raise a
    ConverterException on error otherwise return a hubid"""

    fname = dcfg.text
    hub_id = None
    if 'hub' in dcfg.attrib:
        try:
            hub_id = int(dcfg.attrib['hub'])
        except ValueError:
            raise ConverterException(
                "hub_id for %s is %s (bad)" % (fname, hub_id))

    dpath = os.path.join(domconfig_path, "%s.xml" % fname)
    with open(dpath, 'r') as fd:
        tree = etree.parse(fd)
    root = tree.getroot()

    # collect the name and mbid for every dom in the cfg
    dcfg_dict = {}
    for entry in root.findall('domConfig'):
        name = None

        try:
            try:
                name = entry.attrib['name']
            except KeyError:
                pass

            mbid = entry.attrib['mbid']
        except KeyError:
            raise ConverterException(
                "Missing required attributes in %s@%s" % (fname, dpath))

        if name in dcfg_dict:
            raise ConverterException(
                "Duplicate entry for %s in %s@%s" % (name, fname,dpath))

        dcfg_dict[mbid] = name

    # lookup the string information for all of these doms
    expected_string = hub_id
    for mbid, name in dcfg_dict.items():
        if mbid not in domgeom:
            raise ConverterException(
                "Missing mbid for %s in %s@%s" % (name, fname, dpath))

        dom_string = domgeom[mbid].string()
        if expected_string is None:
            expected_string = dom_string
        elif expected_string != dom_string:
            raise ConverterException(
                "Bad string: %s(%s) in %s@%s" % (dom_string, expected_string,
                                                 name, dpath))

    correct_hubid = expected_string

    return correct_hubid


def parse_dom_config_list(fname, domgeom, config_path=None):
    """Take a run configuration file, pull out all
    the domConfigList elements and ensure that we have a good
    hubid for all domconfiglist elements.

    Return a dictionary of hubid mapped to domconfigfile name"""

    # get the domconfig file path
    if config_path is None:
        dom_config_path = os.path.join(find_pdaq_config(),
                                       'domconfigs')
    else:
        dom_config_path = os.path.join(config_path,
                                       'domconfigs')

    with open(fname, 'r') as fd:
        tree = etree.parse(fd)

    dcfg_dict = {}
    root = tree.getroot()
    dcfgs = root.findall('domConfigList')
    for cfg in dcfgs:
        # validate the domconfig file to make
        # sure that the hub id matches
        hubid = domconfig_gethubid(cfg, domgeom,
                                   dom_config_path)
        dcfg_dict[hubid] = cfg.text

    return dcfg_dict


def compare_hs(obj1, obj2):
    """Compare two hit spool elements"""

    child1 = obj1.getchildren()
    child2 = obj2.getchildren()

    if len(child1) != len(child2):
        # different number of children
        return False

    for cobj1 in child1:
        matched = False
        for cobj2 in child2:
            if cobj1.tag == cobj2.tag and \
                    cobj1.attrib == cobj2.attrib and \
                    cobj1.text == cobj2.text:
                matched = True
                break
        if not matched:
            return False
    return True


def getdefault_hs(fname):
    """figure out what to use for hitspool defaults"""

    with open(fname, 'r') as fd:
        tree = etree.parse(fd)

    root = tree.getroot()
    hubs = root.findall('stringHub')

    default_hs = {'hitspool': {'__children__': {'enabled': ['False']}}}
    default_hs = xml_dict.dict_xml_tree(default_hs)
    if len(hubs) == 0:
        return default_hs

    hub_dict = {}
    hub_list = []
    for hub in hubs:
        if 'hubId' not in hub.attrib:
            raise ConverterException("Stringhub without a hub id %d" % fname)

        hub_id = int(hub.attrib['hubId'])
        if hub_id in hub_dict:
            raise ConverterException("Duplicate hub id")

        # if the hitspool tag exists
        hs = hub.findall('hitspool')
        if len(hs) > 1:
            raise ConverterException(
                "Multiple hitpool tags in a stringhub %s" % fname)
        elif len(hs) == 1:
            hub_dict[hub_id] = hs[0]

    # stringhub entries but no hitspool
    # return the default entry
    if len(hub_dict) == 0:
        return default_hs

    hub_list = hub_dict.items()
    hub_match = {}
    for id1, hs1 in hub_list:
        match_ids = []
        for id2, hs2 in hub_list[1:]:
            if compare_hs(hs1, hs2):
                match_ids.append(id2)

        hub_match[id1] = len(match_ids)

    if len(hub_match) == 0:
        return default_hs

    default_hs_idx = max(hub_match.iteritems(),
                         key=operator.itemgetter(1))[0]

    default_hs = hub_dict[default_hs_idx]
    return default_hs


def find_runconfig(fname, config_path=None):
    """Try and find a matching runconfig file"""

    base_name, extension = os.path.splitext(fname)
    config_name = fname
    if extension != '.xml':
        config_name = "%s.xml" % base_name

    if not os.path.exists(config_name):
        if config_path is None:
            config_path = find_pdaq_config()
        config_name = os.path.join(config_path,
                                   os.path.basename(config_name))

    return config_name


def convert(in_file, out_dir, domgeom=None, config_path=None):
    """Convert a run configuration file to the
    new format.  For performance allow an instance of the
    dom geometry class to be passed into the converter"""

    if domgeom is None:
        default_dom_geom = DefaultDomGeometryReader.parse(translateDoms=True)
        domgeom = default_dom_geom.getDomIdToDomDict()

    # attempt to find a matching runconfig
    in_file = find_runconfig(in_file, config_path)

    # get the config files for every hub id
    hubid_to_cfg_dict = parse_dom_config_list(in_file, domgeom,
                                              config_path)

    # figure out what the default hitspool options should look like
    default_hs = getdefault_hs(in_file)

    # get the default dict
    default_hs_dict = xml_dict.xml_fmt(default_hs)
    default_hs_dict = default_hs_dict['hitspool']

    # get the run configuration dictionary
    runcfg_dict = xml_dict(in_file)

    # delete all domconfigList elements
    try:
        del runcfg_dict.xml_dict['runConfig']['__children__']['domConfigList']
    except KeyError:
        # must not have been any domConfigList entries
        pass

    # add in the appropriate config file parameter to all existing stringHub
    # tags..  note that there might not BE stringhub tags, or they might not
    # all exist, so fix that.
    if 'runConfig' not in runcfg_dict.xml_dict:
        raise ConverterException('Missing required runConfig tag')
    if '__children__' not in runcfg_dict.xml_dict['runConfig']:
        raise ConverterException('RunConfig with no children not valid')
    if 'stringHub' not in runcfg_dict.xml_dict['runConfig']['__children__']:
        runcfg_dict.xml_dict['runConfig']['__children__']['stringHub'] = []

    hub_count = 0
    hubs = runcfg_dict.xml_dict['runConfig']['__children__']['stringHub']
    new_hubs = []
    for hub in hubs:
        hub_id = int(get_attrib(hub, 'hubId'))
        try:
            cfg_file = hubid_to_cfg_dict[hub_id]
        except KeyError:
            # sps-IC86-hitspool-15-sec-interval-V219-no07.xml
            # has a commented out domConfigList but has the matching
            # stringHub element.  Dave says this should print a warning but
            # not be a failure
            print >> sys.stderr, \
                ("WARNING: %s stringHub element %d"
                 " missing a domConfigList") % (in_file, hub_id)
            continue

        set_attrib(hub, 'domConfig', cfg_file)

        # so if the hub has a hitspool child that
        # is the default delete it
        try:
            hub_hitspool = hub['__children__']['hitspool'][0]
            if hub_hitspool == default_hs_dict:
                del hub['__children__']['hitspool']
                if len(hub['__children__']) == 0:
                    del hub['__children__']
        except KeyError:
            # no hitspool child for this hub, ignore
            pass

        # keep track of the hubs that we've processed
        del hubid_to_cfg_dict[hub_id]
        hub_count += 1
        new_hubs.append(hub)

    # new hubs will not include hubs that are missing domconfig info
    runcfg_dict.xml_dict['runConfig']['__children__']['stringHub'] = new_hubs

    # we've now altered any existing stringhub elements
    # add in the stringhub elements that have not existed
    for hub_id, cfg_name in hubid_to_cfg_dict.items():
        str_hub_dict = {'__attribs__': {'domConfig': cfg_name,
                                        'hubId': "%d" % hub_id}}
        runcfg_dict.xml_dict['runConfig'][\
            '__children__']['stringHub'].append(str_hub_dict)
        hub_count += 1

    # put the hubs in hubid order
    runcfg_dict.xml_dict['runConfig']['__children__']['stringHub'].sort(
        key=lambda a: int(get_attrib(a, 'hubId')),
        reverse=False)

    # add in the default hitspool entries
    # only if there are actually hubs defined for
    # this runconfig ( thank you replay-ic22-it4.xml )
    if hub_count > 0:
        runcfg_dict.xml_dict['runConfig'][\
            '__children__']['hitspool'] = [default_hs_dict]

    # filter out any commented out domConfigList entries
    # requested by dave
    if Comment in runcfg_dict.xml_dict['runConfig']['__children__']:
        comments = runcfg_dict.xml_dict['runConfig']['__children__'][Comment]
        comments_tmp = copy.deepcopy(comments)
        for comment_text in comments:
            if re.search('<domConfigList', comment_text):
                comments_tmp.remove(comment_text)
        runcfg_dict.xml_dict['runConfig'][\
            '__children__'][Comment] = comments_tmp

    # print out the converted xml file
    if out_dir == "-":
        print runcfg_dict
    else:
        in_file_basename = os.path.basename(in_file)
        out_file = os.path.join(out_dir,
                                in_file_basename)
        with open(out_file, 'w') as fd:
            print >> fd, runcfg_dict


def main():
    import argparse
    parse = argparse.ArgumentParser()

    parse.add_argument("-o", "--output", dest="output", default="-",
                       help="Output directory name ( - means stdout )")
    parse.add_argument("-d", "--configpath", dest="configpath",
                       help="Config directory")

    args = parse.parse_args()

    geom_fname=None
    if args.configpath is not None:
        geom_fname = os.path.join(args.configpath,
                                  'default-dom-geometry.xml')

    default_dom_geom = DefaultDomGeometryReader.parse(fileName=geom_fname,
                                                      translateDoms=True)
    domgeom = default_dom_geom.getDomIdToDomDict()


    for cfg in args.positional:
        try:
            convert(cfg,
                    args.output, domgeom, args.configpath)
        except IOError as ioe:
            print "Config file error: %s" % cfg
            print "IO ERROR: ", ioe


if __name__ == "__main__":
    main()
