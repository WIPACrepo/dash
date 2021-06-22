#!/usr/bin/env python


import os

from xml.dom import Node


class XMLError(Exception):
    "General XMLParser error"


class XMLFormatError(XMLError):
    "Formatting error encountered by XMLParser"


class XMLBadFileError(XMLError):
    "Bad file encountered by XMLParser"


class XMLParser(object):

    @staticmethod
    def build_path(config_dir, config_name, suffix='.xml'):
        file_name = os.path.join(config_dir, config_name)
        if os.path.exists(file_name):
            return file_name
        if not file_name.endswith(suffix):
            file_name += suffix
            if os.path.exists(file_name):
                return file_name
        return None

    @classmethod
    def get_attribute(cls, node, attr_name, default_val=None):
        "Return the text from this node's attribute"

        if node.attributes is not None:
            try:
                found = attr_name in node.attributes
            except KeyError:
                # Python2 xml.dom.Node doesn't support "name in attributes"
                found = node.attributes.has_key(attr_name)

            # return named attribute value
            if found:
                return node.attributes[attr_name].value

        return default_val

    @classmethod
    def get_child_nodes(cls, node, name):
        if node.childNodes is not None:
            for kid in node.childNodes:
                if kid.nodeType == Node.ELEMENT_NODE and kid.nodeName == name:
                    yield kid

    @classmethod
    def get_child_text(cls, node, strict=False):
        "Return the text from this node's child"

        # pylint: disable=len-as-condition
        if strict and (node.childNodes is None or len(node.childNodes) == 0):
            raise XMLFormatError("No %s child nodes" %
                                 cls.fix_node_name(node))
        # pylint: enable=len-as-condition

        text = None
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                if text is not None:
                    raise XMLFormatError("Found multiple %s text nodes" %
                                         cls.fix_node_name(node))
                text = kid.nodeValue
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if strict:
                if kid.nodeType == Node.ELEMENT_NODE:
                    raise XMLFormatError("Unexpected %s child <%s>" %
                                         (cls.fix_node_name(node),
                                          cls.fix_node_name(kid)))

                raise XMLFormatError("Found unknown %s node <%s>" %
                                     (cls.fix_node_name(node),
                                      cls.fix_node_name(kid)))

        if strict and text is None:
            raise XMLFormatError("No text child node for %s" %
                                 cls.fix_node_name(node))

        return text

    @classmethod
    def get_node_xxx(cls, node, name):
        """Get single subnode named 'name'"""
        kids = node.getElementsByTagName(name)
        if len(kids) < 1:  # pylint: disable=len-as-condition
            return None

        if len(kids) > 1:
            raise XMLFormatError('Multiple <%s> nodes found' % name)

        return kids[0]

    @classmethod
    def fix_node_name(cls, node):
        node_name = '<%s>' % str(node.nodeName)
        if node_name == '<#document>':
            node_name = 'top-level'
        return node_name

    @classmethod
    def get_value(cls, node, name, default_val=None, strict=False):
        """
        Get text value of either attribute (<node name=xxx/>)
        or subnode (<node><name>xxx</name></node>).  If neither is found,
        return default_val
        """
        attr_val = cls.get_attribute(node, name)
        if attr_val is not None:
            # return named attribute value
            return attr_val

        kids = node.getElementsByTagName(name)
        if len(kids) < 1:  # pylint: disable=len-as-condition
            # if no named attribute or node, return default value
            return default_val

        if len(kids) > 1:
            raise XMLFormatError('Multiple <%s> nodes found' % name)

        val = cls.get_child_text(kids[0], strict=strict)
        if val is None:
            return default_val

        return val

    @staticmethod
    def parse_boolean_string(valstr):
        "Return None if the value is not a valid boolean value"
        if valstr is None:
            return None

        lstr = valstr.lower()
        if lstr in ("true", "yes"):
            return True
        if lstr in ("false", "no"):
            return False
        try:
            val = int(valstr)
            return val == 0
        except ValueError:
            pass

        return None
