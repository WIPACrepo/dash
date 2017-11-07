"""A set of utilities that aims at making accessing xml files a little easier
xml_dict will transform an xml file into a python dictionary.  See the
associated doctests for xml_fmt or dict_xml_tree for examples of how this
works.  The two functions contained here are for accessing attributes or
values of the root element of the python dictionary passed to them."""

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
    if isinstance(xdict, list) and len(xdict) > 0:
        return xdict[0]
    if isinstance(xdict, str):
        return xdict

    if '__contents__' not in xdict:
        raise AttributeError("No content value")

    return xdict['__contents__']


class xml_dict(object):
    def __init__(self, fname):
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(fname, parser)

        root = tree.getroot()

        self.xml_dict = xml_dict.xml_fmt(root)
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
        >>> xml_dict.xml_fmt(tree.getroot()) # doctest: +NORMALIZE_WHITESPACE
        {'runCfg': {'__children__': {'domConfigList': [{'__attribs__': {'hub': '5'},
        '__contents__': 'spts-something'}]}}}
        """

        ret = {}
        attribs = dict(parent_element.items())

        # if the parent element has no children,
        # no attributes and only content, just set it to
        # be the contents
        if len(attribs) == 0 and\
                len(parent_element) == 0:
            return parent_element.text

        ret[parent_element.tag] = {}

        # if the root element add root comments
        if parent_element.getroottree().getroot() == parent_element:
            tmp = []
            c = parent_element.getprevious()
            while c is not None:
                if c.tag == Comment:
                    tmp.insert(0, c.text)
                c = c.getprevious()
            if len(tmp) > 0:
                ret['__root_comments__'] = tmp

        if len(attribs) > 0:
            ret[parent_element.tag]['__attribs__'] = attribs

        if parent_element.text is not None and \
                not parent_element.text.isspace():
            ret[parent_element.tag]['__contents__'] = parent_element.text

        tmp = {}
        for child in parent_element:
            child_dict = xml_dict.xml_fmt(child)
            if child.tag not in tmp:
                tmp[child.tag] = []
            if child_dict:
                if isinstance(child_dict, dict):
                    tmp[child.tag].append(child_dict[child.tag])
                else:
                    tmp[child.tag].append(child_dict)

        if len(tmp) > 0:
            ret[parent_element.tag]['__children__'] = tmp

        return ret

    @staticmethod
    def dict_xml_tree(elem_dict, root=None, debug=False):
        """xml_fmt takes an XML file and outputs a specially formatted python
        dictionary.  If you pass that dictionary to this method it will return
        an lxml element tree.  That can be handed off to 'toString()' to
        reproduce a human readable xml file

        >>> xml_d = {'runCfg': {'__children__': {'domConfigList': [{'__attribs__': {'hub': '5'}, '__contents__': 'spts-something'}]}}}
        >>> xml_dict.toString(xml_d, pretty_print=False)
        '<?xml version=\\'1.0\\' encoding=\\'ASCII\\'?>\\n<runCfg><domConfigList hub="5">spts-something</domConfigList></runCfg>'
        """

        try:
            tag, contents = next(elem_dict.iteritems())
        except Exception:
            raise

        debug = tag != "runConfig" and tag != "runComponent" and \
                tag != "stringHub"
        import sys
        from stacktrace import stacktrace
        if debug:
            print >>sys.stderr, "EDict (root %s)" % (root, )
            print >>sys.stderr, "..... keys %s" % (elem_dict.keys())
            print >>sys.stderr, " :: %s" % (stacktrace(), )
            print >>sys.stderr, "----- tag %s contents <%s>" % \
                (tag, type(contents).__name__)
        if root is None:
            if debug:
                print >>sys.stderr, "KidNoRoot"
            root_tag = elem_dict.keys()
            if '__root_comments__' in root_tag:
                root_tag.remove('__root_comments__')
            root_tag = root_tag[0]
            contents = elem_dict[root_tag]
            elem = etree.Element(root_tag)

            if '__root_comments__' in elem_dict:
                for comment_text in elem_dict['__root_comments__']:
                    c = Comment(comment_text)
                    elem.addprevious(c)
        else:
            if debug:
                print >>sys.stderr, "KidRoot"
            elem = etree.SubElement(root, tag)

        if not isinstance(contents, dict) or \
           ('__attribs__' not in contents and
            '__children__' not in contents and
            '__contents__' not in contents):
            if debug:
                print >>sys.stderr, "KidAddText"
            elem.text = contents
            return elem

        # record all of the element attributes
        if '__attribs__' in contents:
            if debug:
                print >>sys.stderr, "KidAttr"
            for (key, value) in contents['__attribs__'].iteritems():
                elem.set(key, value)

        # record the contents
        if '__contents__' in contents and \
           (isinstance(contents['__contents__'], str) or
            isinstance(contents['__contents__'], unicode)):
            if debug:
                print >>sys.stderr, "KidRepl <%s> with <%s>" % \
                    (type(contents).__name__,
                     type(contents['__contents__']).__name__)
            elem.text = contents['__contents__']

        # iterate through children if there are any
        if '__children__' not in contents:
            return elem

        if debug:
            print >>sys.stderr, "KidContents <%s>" % \
                (type(contents).__name__, )
            print >>sys.stderr, "v"*40
        if not isinstance(contents, dict):
            if debug:
                print >>sys.stderr, "NotADict <%s>%s" % \
                    (type(contents).__name__, contents)
        else:
            for child_name, child_desc in contents['__children__'].iteritems():
                if debug:
                    print >>sys.stderr, "Kid %s desc <%s>%s" % \
                        (child_name, type(child_desc).__name__, child_desc)
        if debug:
            print >>sys.stderr, "^"*40
        for child_name, child_desc in contents['__children__'].iteritems():
            if debug:
                print >>sys.stderr, "XXXKid  name %s desc <%s>" % \
                    (child_name, type(child_desc).__name__)
            # a special case.  if the child name is a Comment then
            # build up all the comments
            if child_name == Comment:
                if debug:
                    print >>sys.stderr, "XXXComment"
                for comment_text in child_desc:
                    c = Comment(comment_text)
                    elem.append(c)
            # a special case..  if the child_desc is a list with a string
            # element then build the child appropriately
            elif isinstance(child_desc, list):
                if len(child_desc) == 1 and \
                   (isinstance(child_desc[0], str) or child_desc[0] is None):
                    if debug:
                        print >>sys.stderr, "XXXListOne"
                    child_element = etree.SubElement(elem, child_name)
                    child_element.text = child_desc[0]
                else:
                    for entry in child_desc:
                        if debug:
                            print >>sys.stderr, "XXXListMulti <%s>%s" % \
                                (type(entry).__name__, entry)
                        xml_dict.dict_xml_tree({child_name: entry}, root=elem,
                                               debug=debug)
            else:
                print >>sys.stderr, "Not handling <%s>%s" % \
                    (type(child_desc).__name__, child_desc)

        return elem

    @staticmethod
    def toString(info_dict, pretty_print=True, debug=False):
        root = xml_dict.dict_xml_tree(info_dict, debug=debug)
        tree = etree.ElementTree(root)
        return etree.tostring(tree,
                              method="xml",
                              xml_declaration=True,
                              pretty_print=pretty_print)

    def __str__(self):
        return self.toString(self.xml_dict)


if __name__ == "__main__":
    import doctest
    doctest.testmod()
