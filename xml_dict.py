#!/usr/bin/env python

"""
A set of utilities that aims at making accessing xml files a little easier
XMLDict will transform an xml file into a python dictionary.  See the
associated doctests for xml_fmt or dict_xml_tree for examples of how this
works.  The two functions contained here are for accessing attributes or
values of the root element of the python dictionary passed to them.
"""

from __future__ import print_function

import sys

from lxml import etree
from lxml.etree import Comment


def get_attrib(xdict, attrib_name):
    if '__attribs__' not in xdict or \
            attrib_name not in xdict['__attribs__']:
        raise AttributeError("Missing attribute %s" % attrib_name)

    return xdict['__attribs__'][attrib_name]


def set_attrib(xdict, attrib_name, value):
    if '__attribs__' not in xdict:
        xdict['__attribs__'] = {}
    xdict['__attribs__'][attrib_name] = value


def get_value(xdict):
    if isinstance(xdict, list) and \
      len(xdict) > 0:  # pylint: disable=len-as-condition
        return xdict[0]
    if isinstance(xdict, str):
        return xdict

    if '__contents__' not in xdict:
        raise AttributeError("No content value")

    return xdict['__contents__']


class XMLDict(object):
    def __init__(self, fname):
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(fname, parser)

        root = tree.getroot()

        self.xml_dict = XMLDict.xml_fmt(root)
        self.encoding = tree.docinfo.encoding

    @staticmethod
    def xml_fmt(parent_element):
        """Take an xml element tree and produce a specially formatted
        python dictionary.

        To see how to parse the an xml file and get the element tree root
        see the __init__ method above

        >>> from StringIO import StringIO
        >>> xml = '<runCfg><domConfigList hub="5">spts-something</domConfigList></runCfg>'
        >>> tree = etree.parse(StringIO(xml), etree.XMLParser(remove_blank_text=True))
        >>> XMLDict.xml_fmt(tree.getroot()) # doctest: +NORMALIZE_WHITESPACE
        {'runCfg': {'__children__': {'domConfigList': [{'__attribs__': {'hub': '5'},
        '__contents__': 'spts-something'}]}}}
        """

        ret = {}
        attribs = dict(list(parent_element.items()))

        # if the parent element has no children,
        # no attributes and only content, just set it to
        # be the contents
        # pylint: disable=len-as-condition
        if len(attribs) == 0 and \
          len(parent_element) == 0:  # pylint: disable=len-as-condition
            return parent_element.text
        # pylint: enable=len-as-condition

        ret[parent_element.tag] = {}

        # if the root element add root comments
        if parent_element.getroottree().getroot() == parent_element:
            tmp = []
            prev = parent_element.getprevious()
            while prev is not None:
                if prev.tag == Comment:
                    tmp.insert(0, prev.text)
                prev = prev.getprevious()
            if len(tmp) > 0:  # pylint: disable=len-as-condition
                ret['__root_comments__'] = tmp

        if len(attribs) > 0:  # pylint: disable=len-as-condition
            ret[parent_element.tag]['__attribs__'] = attribs

        if parent_element.text is not None and \
                not parent_element.text.isspace():
            ret[parent_element.tag]['__contents__'] = parent_element.text

        tmp = {}
        for child in parent_element:
            child_dict = XMLDict.xml_fmt(child)
            if child.tag not in tmp:
                tmp[child.tag] = []
            if child_dict:
                if isinstance(child_dict, dict):
                    tmp[child.tag].append(child_dict[child.tag])
                else:
                    tmp[child.tag].append(child_dict)

        if len(tmp) > 0:  # pylint: disable=len-as-condition
            ret[parent_element.tag]['__children__'] = tmp

        return ret

    @staticmethod
    def dict_xml_tree(elem_dict, root=None):
        # pylint: disable=line-too-long
        """xml_fmt takes an XML file and outputs a specially formatted python
        dictionary.  If you pass that dictionary to this method it will return
        an lxml element tree.  That can be handed off to 'to_string()' to
        reproduce a human readable xml file

        >>> xml_d = {'runCfg': {'__children__': {'domConfigList': [{'__attribs__': {'hub': '5'}, '__contents__': 'spts-something'}]}}}
        >>> XMLDict.to_string(xml_d, pretty_print=False)
        '<?xml version=\\'1.0\\' encoding=\\'ASCII\\'?>\\n<runCfg><domConfigList hub="5">spts-something</domConfigList></runCfg>'
        """
        # pylint: enable=line-too-long

        tag, contents = next(iter(list(elem_dict.items())))
        if root is not None:
            elem = etree.SubElement(root, tag)
        else:
            root_tag = list(elem_dict.keys())
            if '__root_comments__' in root_tag:
                root_tag.remove('__root_comments__')
            root_tag = root_tag[0]
            contents = elem_dict[root_tag]
            elem = etree.Element(root_tag)

            if '__root_comments__' in elem_dict:
                for comment_text in elem_dict['__root_comments__']:
                    cobj = Comment(comment_text)
                    elem.addprevious(cobj)

        if not isinstance(contents, dict) or \
           ('__attribs__' not in contents and
            '__children__' not in contents and
            '__contents__' not in contents):
            elem.text = contents
            return elem

        # record all of the element attributes
        if '__attribs__' in contents:
            for (key, value) in list(contents['__attribs__'].items()):
                elem.set(key, value)

        # record the contents
        if '__contents__' in contents and \
          isinstance(contents['__contents__'], (str, unicode)):
            elem.text = contents['__contents__']

        # iterate through children if there are any
        if '__children__' not in contents:
            return elem

        for child_name, child_desc in list(contents['__children__'].items()):
            # a special case.  if the child name is a Comment then
            # build up all the comments
            if child_name == Comment:
                for comment_text in child_desc:
                    cobj = Comment(comment_text)
                    elem.append(cobj)
            # a special case..  if the child_desc is a list with a string
            # element then build the child appropriately
            elif isinstance(child_desc, list):
                if len(child_desc) == 1 and \
                   (isinstance(child_desc[0], str) or child_desc[0] is None):
                    child_element = etree.SubElement(elem, child_name)
                    child_element.text = child_desc[0]
                else:
                    for entry in child_desc:
                        XMLDict.dict_xml_tree({child_name: entry}, root=elem)
            else:
                print("Not handling <%s>%s" %
                      (type(child_desc).__name__, child_desc), file=sys.stderr)

        return elem

    @staticmethod
    def to_string(info_dict, pretty_print=True):
        root = XMLDict.dict_xml_tree(info_dict)
        tree = etree.ElementTree(root)
        outstr = etree.tostring(tree, method="xml", xml_declaration=True,
                                pretty_print=pretty_print)
        if isinstance(outstr, bytes):
            outstr = outstr.decode("utf-8")
        return outstr

    def __str__(self):
        return self.to_string(self.xml_dict)


def main():
    import doctest
    doctest.testmod()


if __name__ == "__main__":
    main()
