#!/usr/bin/env python
"""
classes which convert pDAQ's "database" of static DOM info (found in
`~pdaq/config/default-dom-geometry.xml`) into a set of Python objects, as
well as functions to modify and write out a new XML file 
"""

from __future__ import print_function

import os
import re
import sys

from xml.dom import minidom, Node
from xmlparser import XMLBadFileError, XMLFormatError, XMLParser

from i3helper import Comparable
from locate_pdaq import find_pdaq_config


def compute_channel_id(string, pos):
    """
    Compute the channel ID for a DOM's (string, position) information
    """
    if string is None or pos is None:
        return None

    if pos < 1 or pos > DomGeometry.MAX_POSITION:
        raise Exception("Impossible position %d" % pos)

    kstring = string % 1000
    if kstring < 0 or kstring > DomGeometry.MAX_STRING:
        raise Exception("Impossible string %d" % string)

    if pos > 64:
        return (6000 + ((kstring - 1) * 2) + (pos - 65)) & 0xffff

    return ((kstring * 64) + (pos - 1)) & 0xffff


def decode_channel_id(chan_id):
    "Translate a channel ID into a DOM's (string, position) information"
    if chan_id is None:
        return None

    if chan_id >= 6000:
        # scinillator IDs
        pos = 65 + (chan_id % 2)
        kstr = (chan_id - 6000) / 2
        return (kstr + 1, pos)

    return (chan_id / 64, (chan_id % 64) + 1)


class DomGeometryException(Exception):
    "General DOMGeometry exception"


class DomGeometry(Comparable):
    "maximum possible DOM position"
    MAX_POSITION = 66
    "maximum SPS string number"
    MAX_STRING = 86
    "maximum possible channel ID"
    MAX_CHAN_ID = 1000 * MAX_POSITION
    "start of range for icetop hub IDs"
    BASE_ICETOP_HUB_NUM = 200

    "Data for a single DOM"
    def __init__(self, string, pos, mbid, name, prod_id, chan_id=None,
                 x=None, y=None, z=None):
        self.__string = string
        self.__pos = pos
        self.__mbid = mbid
        self.__name = name
        self.__prod_id = prod_id
        self.__chan_id = chan_id
        self.__x = x
        self.__y = y
        self.__z = z

        self.__desc = None

        self.__orig_order = None
        self.__orig_string = None

    def __str__(self):
        return "%s[%s] %s" % (self.__mbid, self.__name, self.location())

    @property
    def channel_id(self):
        return self.__chan_id

    @channel_id.setter
    def channel_id(self, chan_id):
        if chan_id > self.MAX_CHAN_ID:
            raise DomGeometryException("Bad channel ID %d for %s" %
                                       (chan_id, self))
        self.__chan_id = chan_id

    @property
    def compare_key(self):
        return (self.original_order, self.string, self.original_string,
                self.pos)

    @property
    def description(self):
        if self.__desc is None:
            return "-"
        return self.__desc

    @description.setter
    def description(self, desc):
        if desc is None or desc == "-" or desc == "NULL":
            self.__desc = None
        else:
            self.__desc = desc

    @property
    def is_icetop(self):
        if self.__orig_string is not None:
            strnum = self.__orig_string
        else:
            strnum = self.__string

        return 1 <= strnum <= DomGeometry.MAX_STRING and \
          61 <= self.__pos <= 64

    @property
    def is_inice(self):
        if self.__orig_string is not None:
            strnum = self.__orig_string
        else:
            strnum = self.__string

        return 1 <= strnum <= DomGeometry.MAX_STRING and 1 <= self.__pos <= 60

    @property
    def is_real_dom(self):
        if self.__orig_string is not None:
            strnum = self.__orig_string
        else:
            strnum = self.__string

        return 1 <= strnum <= DomGeometry.MAX_STRING and 1 <= self.__pos <= 64

    @property
    def is_scintillator(self):
        if self.__orig_string is not None:
            strnum = self.__orig_string
        else:
            strnum = self.__string

        return 1 <= strnum <= DomGeometry.MAX_STRING and 65 <= self.__pos <= 66

    def location(self):
        if self.__orig_string is not None:
            strnum = self.__orig_string
        else:
            strnum = self.__string

        if strnum is not None:
            if self.__pos is not None:
                return "%02d-%02d" % (strnum, self.__pos)
            return "%02d-??" % (strnum, )

        if self.__pos is not None:
            return "??-%02d" % (self.__pos, )

        return "[Not Deployed]"

    @property
    def mbid(self):
        return self.__mbid

    @mbid.setter
    def mbid(self, mbid):
        self.__mbid = mbid

    @property
    def name(self):
        return self.__name

    @name.setter
    def name(self, name):
        self.__name = name

    @property
    def original_order(self):
        return self.__orig_order

    @original_order.setter
    def original_order(self, num):
        self.__orig_order = num

    @property
    def original_string(self):
        return self.__orig_string

    @original_string.setter
    def original_string(self, num):
        self.__orig_string = num

    @property
    def pos(self):
        return self.__pos

    @pos.setter
    def pos(self, pos):
        if pos < 1 or pos > self.MAX_POSITION:
            raise DomGeometryException("Bad position %d for %s" % (pos, self))
        self.__pos = pos

    @property
    def prod_id(self):
        return self.__prod_id

    @prod_id.setter
    def prod_id(self, prod_id):
        self.__prod_id = prod_id

    def rewrite(self, verbose=False, rewrite_old_icetop=False):
        if self.__pos is None:
            print("Not rewriting DOM %s" % (self, ), file=sys.stderr)
            return False

        base_num = self.__string % 1000

        if self.__pos < 1 or self.__pos > self.MAX_POSITION:
            if verbose:
                print("Bad position %d for %s" %
                      (self.__pos, self), file=sys.stderr)
            return False

        orig_str = base_num
        if self.__orig_string is not None:
            orig_str = self.__orig_string

        if orig_str <= self.MAX_STRING or self.__orig_order is not None:
            if self.__pos > 0 and orig_str <= self.MAX_STRING:
                new_chan_id = compute_channel_id(orig_str, self.__pos)
                if verbose and self.__chan_id is not None and \
                   self.__chan_id != new_chan_id:
                    print("Rewriting %s channel ID from %s to %d" %
                          (self.__name, self.__chan_id, new_chan_id),
                          file=sys.stderr)
                self.__chan_id = new_chan_id
            elif verbose and self.__chan_id is None:
                print("Not setting channel ID for %s" % (self.__name, ),
                      file=sys.stderr)

        changed_string = False
        if 0 < base_num <= self.MAX_STRING and \
          self.__pos <= 60:
            return False
        if base_num > self.BASE_ICETOP_HUB_NUM and self.__pos > 60:
            return False
        if not rewrite_old_icetop and base_num > self.MAX_STRING and \
          self.__pos > 60:
            return False

        if self.__pos <= 60:
            if base_num != 0 or self.__pos != 1:
                new_num = base_num
            else:
                new_num = 208
        elif self.__pos <= 64:
            if rewrite_old_icetop and base_num > self.MAX_STRING and \
               base_num < self.BASE_ICETOP_HUB_NUM:
                new_num = base_num % 10 + self.BASE_ICETOP_HUB_NUM
            else:
                try:
                    new_num \
                      = DefaultDomGeometry.get_icetop_string(self.__string)
                except XMLFormatError:
                    new_num = self.__string
        elif self.__pos <= 66:
            try:
                new_num \
                  = DefaultDomGeometry.get_scintillator_string(self.__string)
            except XMLFormatError:
                new_num = self.__string
        else:
            raise XMLFormatError("Bad position %s for %s" % (self.__pos, self))

        if new_num != base_num:
            new_num = (self.__string / 1000) * 1000 + (new_num % 1000)
            self.string = new_num
            changed_string = True

        return changed_string

    @property
    def string(self):
        return self.__string

    @string.setter
    def string(self, str_num):
        tmp_num = self.__string
        self.__string = str_num
        if self.__orig_string is None:
            self.__orig_string = tmp_num
        elif self.__orig_string != tmp_num:
            raise DomGeometryException(("Cannot overwrite original string %d" +
                                        " with %d for %s") %
                                       (self.__orig_string, tmp_num, self))

    def update(self, dom, verbose=False):
        "Copy missing info from DOM argument"
        if self.__mbid is None:
            self.__mbid = dom.mbid
        elif verbose and dom.string < self.BASE_ICETOP_HUB_NUM and \
             dom.mbid is not None and self.__mbid != dom.mbid:
            print("Not changing DOM %s MBID from \"%s\" to \"%s\"" %
                  (self, self.__mbid, dom.mbid), file=sys.stderr)

        if self.__name is None:
            self.__name = dom.name
        elif verbose and dom.string < self.BASE_ICETOP_HUB_NUM and \
             dom.name is not None and self.__name != dom.name:
            print("Not changing DOM %s name from \"%s\" to \"%s\"" %
                  (self, self.__name, dom.name), file=sys.stderr)

        if self.__prod_id is None:
            self.__prod_id = dom.prod_id
        elif verbose and dom.string < self.BASE_ICETOP_HUB_NUM and \
             dom.prod is not None and self.__prod_id != dom.prod:
            print("Not changing DOM %s prodID from \"%s\" to \"%s\"" %
                  (self, self.__prod_id, dom.prod), file=sys.stderr)

        if self.__chan_id is None:
            self.__chan_id = dom.chan_id
        elif verbose and dom.string < self.BASE_ICETOP_HUB_NUM and \
             dom.chan_id is not None and self.__chan_id != dom.chan_id:
            print("Not changing DOM %s channel ID from %d to %d" %
                  (self, self.__chan_id, dom.chan_id), file=sys.stderr)

        if self.__orig_string is None:
            self.__orig_string = dom.original_string
        elif verbose and dom.original_string is not None and \
             self.__orig_string != dom.original_string:
            print("Not changing DOM %s original string from %d to %d" %
                  (self, self.__orig_string, dom.original_string),
                  file=sys.stderr)

    def validate(self):
        if self.__name is None and self.__mbid is None:
            if self.__string is None and self.__pos is None:
                raise XMLFormatError("Found uninitialized DOM %s" % str(self))
            raise XMLFormatError("No name or mainboard ID for %s" %
                                 (self.location(), ))

        if self.__name is None:
            raise XMLFormatError("DOM %s is missing name" % (self.__mbid, ))

        if self.__mbid is None:
            raise XMLFormatError("DOM %s is missing mainboard ID" %
                                 (self.__name, ))

        if self.__string is None:
            if self.__pos is not None:
                raise XMLFormatError("DOM %s is missing string number" %
                                     (self.__name, ))
        elif self.__pos is None:
            raise XMLFormatError("DOM %s in string %s is missing position" %
                                 (self.__name, self.__string))

    @property
    def x_coord(self):
        return self.__x

    @x_coord.setter
    def x_coord(self, coord):
        self.__x = coord

    @property
    def y_coord(self):
        return self.__y

    @y_coord.setter
    def y_coord(self, coord):
        self.__y = coord

    @property
    def z_coord(self):
        return self.__z

    @z_coord.setter
    def z_coord(self, coord):
        self.__z = coord


class String(object):
    def __init__(self, num):
        self.__number = num
        self.__rack = None
        self.__partition = None
        self.__doms = []

    def __iter__(self):
        return iter(sorted(self.__doms, key=lambda x: x.pos))

    def __str__(self):
        if self.__rack is None:
            rstr = ""
        else:
            rstr = "R%s " % (self.__rack, )

        if self.__partition is None:
            pstr = ""
        else:
            pstr = "%s " % (self.__partition, )

        return "String#%s[%s%sDOMS*%d]" % \
            (self.__number, rstr, pstr, len(self.__doms))

    def add(self, dom):
        self.__doms.append(dom)

    def delete(self, dom):
        found = False
        for i in range(len(self.__doms)):
            cur = self.__doms[i]
            if dom.pos <= 60 and dom.pos == cur.pos:
                found = True
            elif dom.mbid is not None and cur.mbid is not None and \
                 dom.mbid == cur.mbid:
                found = True
            elif dom.prod_id is not None and cur.prod_id is not None and \
                 dom.prod_id == cur.prod_id:
                found = True

            if found:
                del self.__doms[i]
                return

        if dom.mbid is not None or dom.name is not None:
            print("Could not delete %s" % str(dom), file=sys.stderr)

    @property
    def doms(self):
        return self.__doms[:]

    @property
    def number(self):
        return self.__number

    @property
    def partition(self):
        return self.__partition

    @partition.setter
    def partition(self, partition):
        if self.__partition is not None and self.__partition != partition:
            print("Changing string %d partition %s to %s" %
                  (self.__number, self.__partition, partition),
                  file=sys.stderr)
        self.__partition = partition

    @property
    def rack(self):
        return self.__rack

    @rack.setter
    def rack(self, rack):
        if self.__rack is not None and self.__rack != rack:
            print("Changing string %d rack %d to %d" %
                  (self.__number, self.__rack, rack), file=sys.stderr)
        self.__rack = rack


class DefaultDomGeometry(object):
    FILENAME = "default-dom-geometry.xml"

    STRING_COMMENT = {
        2002: "MDFL3 DOMs",
        2012: "MDFL2 DOMs",
        2022: "ABSCAL DOMs",
    }

    def __init__(self, translate_doms=True):
        self.__strings = {}
        self.__translate_doms = translate_doms
        self.__dom_id_to_dom = {}

    @classmethod
    def __dump_coordinate(cls, out, axis, indent, value):
        name = axis + "Coordinate"

        vstr = "%3.2f" % value
        vstr = vstr.rstrip("0")
        if vstr.endswith("."):
            vstr += "0"

        print("%s<%s>%s</%s>" % (indent, name, vstr, name), file=out)

    def add_dom(self, dom):
        self.__strings[dom.string].add(dom)

        if self.__translate_doms:
            mbid = dom.mbid
            if mbid is not None:
                if mbid in self.__dom_id_to_dom:
                    old_num = self.__dom_id_to_dom[mbid].string
                    if old_num != dom.string:
                        print("DOM %s belongs to both string %d and %d" %
                              (mbid, old_num, dom.string), file=sys.stderr)

                self.__dom_id_to_dom[mbid] = dom

    def add_string(self, string_num, error_on_multi=True):
        if string_num not in self.__strings:
            self.__strings[string_num] = String(string_num)
        elif error_on_multi:
            raise XMLFormatError("Found multiple entries for string %d" %
                                 string_num)

    def delete_dom(self, string_num, dom):
        if string_num not in self.__strings:
            raise XMLFormatError("String %d does not exist" % string_num)
        self.__strings[string_num].delete(dom)

    def doms(self):
        "Convenience method to list all known DOMs"
        for domlist in self.__strings.values():
            for dom in domlist:
                yield dom

    def dump(self, out=sys.stdout, include_undeployed_doms=False):
        "Dump the string->DOM dictionary in default-dom-geometry format"
        indent = "  "
        dom_indent = indent + indent + indent

        print("<?xml version=\"1.0\" encoding=\"UTF-8\"?>", file=out)
        print("<domGeometry>", file=out)
        for strnum in sorted(self.__strings.keys()):
            dom_list = self.__strings[strnum].doms
            if len(dom_list) == 0:  # pylint: disable=len-as-condition
                continue

            if not include_undeployed_doms and strnum is None:
                # ignore undeployed DOMs
                continue

            print("%s<string>" % indent, file=out)
            if strnum in self.STRING_COMMENT:
                print("%s%s<!-- %s -->" %
                      (indent, indent, self.STRING_COMMENT[strnum]), file=out)
            if strnum is not None:
                print("%s%s<number>%d</number>" % (indent, indent, strnum),
                      file=out)
            else:
                print("%s%s<!-- Undeployed DOMs -->", file=out)

            if strnum is not None and self.__strings[strnum].rack is not None:
                print("%s%s<rack>%d</rack>" %
                      (indent, indent, self.__strings[strnum].rack), file=out)

            if strnum is not None and \
               self.__strings[strnum].partition is not None:
                print("%s%s<partition>%s</partition>" %
                      (indent, indent, self.__strings[strnum].partition),
                      file=out)

            dom_list.sort()
            for dom in dom_list:
                if dom.mbid is None and dom.name is None and \
                   dom.prod_id is None:
                    continue
                print("%s%s<dom>" % (indent, indent), file=out)
                if dom.original_string is not None and \
                   (dom.original_string % 1000) < \
                   DomGeometry.BASE_ICETOP_HUB_NUM and \
                   dom.original_string != dom.string:
                    print("%s<originalString>%d</originalString>" %
                          (dom_indent, dom.original_string), file=out)
                if dom.pos is not None:
                    print("%s<position>%d</position>" %
                          (dom_indent, dom.pos), file=out)
                if dom.channel_id is not None:
                    print("%s<channel_id>%d</channel_id>" %
                          (dom_indent, dom.channel_id), file=out)
                if dom.mbid is not None:
                    print("%s<mainBoardId>%s</mainBoardId>" %
                          (dom_indent, dom.mbid), file=out)
                if dom.name is not None:
                    print("%s<name>%s</name>" % (dom_indent, dom.name),
                          file=out)
                if dom.prod_id is not None:
                    print("%s<productionId>%s</productionId>" %
                          (dom_indent, dom.prod_id), file=out)
                if dom.x_coord is not None:
                    self.__dump_coordinate(out, "x", dom_indent, dom.x_coord)
                if dom.y_coord is not None:
                    self.__dump_coordinate(out, "y", dom_indent, dom.y_coord)
                if dom.z_coord is not None:
                    self.__dump_coordinate(out, "z", dom_indent, dom.z_coord)
                print("%s%s</dom>" % (indent, indent), file=out)

            print("%s</string>" % indent, file=out)
        print("</domGeometry>", file=out)

    def get_dom(self, str_num, pos, prod_id=None, orig_num=None):
        if str_num not in self.__strings:
            return None

        for dom in self.__strings[str_num].doms:
            if dom.pos == pos:
                if orig_num is not None:
                    if dom.original_string is not None and \
                       dom.original_string == orig_num:
                        return dom

                if prod_id is not None:
                    if dom.prod_id == prod_id:
                        return dom

                if prod_id is None and orig_num is None:
                    return dom

        return None

    def get_dom_id_to_dom_dict(self):
        "Get the DOM ID -> DOM object dictionary"
        return self.__dom_id_to_dom

    @staticmethod
    def get_icetop_string(str_num):
        "Translate the in-ice string number to the corresponding icetop hub"
        # FIXME: don't hard-code these string numbers, extract them from
        #        $PDAQ_CONFIG/default-dom-geometry.xml
        if str_num % 1000 == 0 or str_num >= 2000:
            return str_num

        if str_num > 1000:
            return ((((str_num % 100) + 7)) / 8) + 1200

        # SPS map goes here

        fix_num = None
        if str_num in [46, 55, 56, 65, 72, 73, 77, 78]:
            fix_num = 201
        elif str_num in [38, 39, 48, 58, 64, 66, 71, 74]:
            fix_num = 202
        elif str_num in [30, 40, 47, 49, 50, 57, 59, 67]:
            fix_num = 203
        elif str_num in [4, 5, 10, 11, 18, 20, 27, 36]:
            fix_num = 204
        elif str_num in [45, 54, 62, 63, 69, 70, 75, 76]:
            fix_num = 205
        elif str_num in [21, 29, 44, 52, 53, 60, 61, 68]:
            fix_num = 206
        elif str_num in [2, 3, 6, 9, 12, 13, 17, 26]:
            fix_num = 207
        elif str_num in [19, 28, 37]:
            fix_num = 208
        elif str_num in [8, 15, 16, 24, 25, 32, 35, 41]:
            fix_num = 209
        elif str_num in [23, 33, 34, 42, 43, 51]:
            fix_num = 210
        elif str_num in [1, 7, 14, 22, 31, 79, 80, 81]:
            fix_num = 211
        else:
            raise XMLFormatError("Could not find icetop hub for string %d" %
                                 (str_num, ))

        return fix_num

    @staticmethod
    def get_scintillator_string(str_num):
        """
        Translate the in-ice string number to the corresponding
        scintillator hub
        """
        # FIXME: don't hard-code these string numbers, extract them from
        #        $PDAQ_CONFIG/default-dom-geometry.xml
        if str_num in (12, 62, ):
            return 208

        raise XMLFormatError("Could not find scintillator hub for string %d" %
                             (str_num, ))

    def doms_on_string(self, strnum):
        "Get the DOMs on the requested string"
        if strnum not in self.__strings:
            return None
        return self.__strings[strnum].doms

    @property
    def partitions(self):
        "Get the partition->string-number dictionary"
        partitions = {}
        for strnum, strobj in list(self.__strings.items()):
            if strobj.partition is not None:
                if strobj.partition not in partitions:
                    partitions[strobj.partition] = []
                partitions[strobj.partition].append(strnum)
        return partitions

    @property
    def string_numbers(self):
        "Get all known string numbers"
        return self.__strings.keys()

    def string_object(self, string_num):
        "Get all known string numbers"
        if string_num not in self.__strings:
            raise XMLFormatError("String %d does not exist" % string_num)
        return self.__strings[string_num]

    def strings_on_rack(self, racknum):
        "Get the string numbers for all strings on the requested rack"
        strings = []
        for strnum, strobj in list(self.__strings.items()):
            if strobj.rack == racknum:
                strings.append(strnum)
        return strings

    def rewrite(self, verbose=False, rewrite_old_icetop=False):
        """
        Rewrite default-dom-geometry from 64 DOMs per string hub to
        60 DOMs per string hub and 32 DOMs per icetop hub
        """
        str_list = sorted(self.__strings.keys())

        for strnum in str_list:
            dom_list = self.__strings[strnum].doms

            for dom in dom_list:
                if dom.rewrite(verbose=verbose,
                               rewrite_old_icetop=rewrite_old_icetop):
                    self.__strings[strnum].delete(dom)

                    self.add_string(dom.string, error_on_multi=False)
                    self.add_dom(dom)

    def set_partition(self, string_num, partition):
        if string_num not in self.__strings:
            raise XMLFormatError("String %d does not exist" % string_num)
        self.__strings[string_num].partition = partition

    def set_rack(self, string_num, rack):
        if string_num not in self.__strings:
            raise XMLFormatError("String %d does not exist" % string_num)
        self.__strings[string_num].rack = rack

    def update(self, new_dom_geom, verbose=False):
        "Copy missing string, DOM, or DOM info from 'new_dom_geom'"
        keys = list(self.__strings.keys())

        for strnum in new_dom_geom.string_numbers:
            if strnum not in keys:
                self.__strings[strnum] = new_dom_geom.string_object(strnum)
                continue
            for newdom in new_dom_geom.doms_on_string(strnum):
                found_pos = False
                for dom in self.__strings[strnum]:
                    if dom.pos == newdom.pos:
                        found_pos = True
                        if dom.mbid == newdom.mbid:
                            dom.update(newdom, verbose=verbose)
                if not found_pos:
                    self.add_dom(newdom)

    def validate(self):
        names = {}
        locs = {}

        str_keys = sorted(self.__strings.keys())

        for str_num in str_keys:
            for dom in self.__strings[str_num].doms:
                if dom.name not in names:
                    names[dom.name] = dom
                else:
                    print("Found DOM \"%s\" at %s and %s" %
                          (dom.name, dom.location(),
                           names[dom.name].location()), file=sys.stderr)

                if dom.name.startswith("SIM") and \
                   dom.string % 1000 >= 200 and dom.string % 1000 < 299:
                    domnum = int(dom.name[3:])
                    orig_str = int(((domnum - 1) / 64) + 1001)
                    if dom.original_string is None:
                        dom.original_string = orig_str
                    elif dom.original_string != orig_str:
                        print("DOM %s \"%s\" should have origStr %d, not %d" %
                              (dom.location(), dom.name, orig_str,
                               dom.original_string), file=sys.stderr)

                if dom.location() not in locs:
                    locs[dom.location()] = dom
                else:
                    print("Position %s holds DOMS %s and %s" %
                          (dom.location(), dom.name,
                           locs[dom.location()].name), file=sys.stderr)

                if dom.original_string is not None:
                    str_num = dom.original_string
                else:
                    str_num = dom.string

                if str_num % 1000 == 0:
                    # don't bother validating AMANDA entries
                    continue

                new_id = compute_channel_id(str_num, dom.pos)
                if dom.channel_id is None:
                    if dom.pos <= DomGeometry.MAX_POSITION:
                        print("No channel ID for DOM %s \"%s\"" %
                              (dom.location(), dom.name), file=sys.stderr)
                elif new_id != dom.channel_id:
                    print("DOM %s \"%s\" should have channel ID %d, not %d" %
                          (dom.location(), dom.name, new_id, dom.channel_id),
                          file=sys.stderr)
                    dom.channel_id = new_id


class DefaultDomGeometryReader(XMLParser):

    @classmethod
    def __parse_dom_node(cls, string_num, node):
        "Extract a single DOM's data from the default-dom-geometry XML tree"
        if node.attributes is not None \
          and len(node.attributes) > 0:  # pylint: disable=len-as-condition
            raise XMLFormatError("<%s> node has unexpected attributes" %
                                 node.nodeName)

        pos = None
        mbid = None
        name = None
        prod = None
        chan_id = None
        x_coord = None
        y_coord = None
        z_coord = None

        orig_str = None

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "position":
                    pos = int(cls.get_child_text(kid))
                elif kid.nodeName == "mainBoardId":
                    mbid = cls.get_child_text(kid)
                elif kid.nodeName == "name":
                    name = cls.get_child_text(kid)
                elif kid.nodeName == "productionId":
                    prod = cls.get_child_text(kid)
                elif kid.nodeName == "channelId":
                    chan_id = int(cls.get_child_text(kid))
                elif kid.nodeName == "xCoordinate":
                    x_coord = float(cls.get_child_text(kid))
                elif kid.nodeName == "yCoordinate":
                    y_coord = float(cls.get_child_text(kid))
                elif kid.nodeName == "zCoordinate":
                    z_coord = float(cls.get_child_text(kid))
                elif kid.nodeName == "originalString":
                    orig_str = int(cls.get_child_text(kid))
                else:
                    raise XMLFormatError("Unexpected %s child <%s>" %
                                         (node.nodeName, kid.nodeName))
                continue

            raise XMLFormatError("Found unknown %s node <%s>" %
                                 (node.nodeName, kid.nodeName))

        dom = DomGeometry(string_num, pos, mbid, name, prod, chan_id, x_coord,
                          y_coord, z_coord)
        if orig_str is not None:
            dom.original_string = orig_str
        dom.validate()

        return dom

    @classmethod
    def __parse_string_node(cls, geom, node):
        "Extract data from a default-dom-geometry <string> node tree"
        if node.attributes is not None and \
          len(node.attributes) > 0:  # pylint: disable=len-as-condition
            raise XMLFormatError("<%s> node has unexpected attributes" %
                                 node.nodeName)

        string_num = None
        orig_order = 0

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "number":
                    if string_num is not None:
                        raise XMLFormatError("Found multiple <number> nodes" +
                                             " under <string>")
                    string_num = int(cls.get_child_text(kid))
                    geom.add_string(string_num)
                    orig_order = 0
                elif kid.nodeName == "rack":
                    if string_num is None:
                        raise XMLFormatError("Found <rack> before" +
                                             " <number> under <string>")
                    rack = int(cls.get_child_text(kid))
                    geom.set_rack(string_num, rack)
                elif kid.nodeName == "partition":
                    if string_num is None:
                        raise XMLFormatError("Found <partition> before" +
                                             " <number> under <string>")
                    geom.set_partition(string_num, cls.get_child_text(kid))
                elif kid.nodeName == "dom":
                    if string_num is None:
                        raise XMLFormatError("Found <dom> before" +
                                             " <number> under <string>")
                    dom = cls.__parse_dom_node(string_num, kid)

                    dom.original_order = orig_order
                    orig_order += 1

                    geom.add_dom(dom)
                else:
                    print("Ignoring unknown %s child <%s>" %
                          (node.nodeName, kid.nodeName), file=sys.stderr)
                continue

            raise XMLFormatError("Found unknown %s node <%s>" %
                                 (node.nodeName, kid.nodeName))

        if string_num is None:
            raise XMLFormatError("String is missing number")

    @classmethod
    def parse(cls, config_dir=None, file_name=None, translate_doms=False):
        if config_dir is None:
            config_dir = find_pdaq_config()

        if file_name is None:
            file_name = os.path.join(config_dir, DefaultDomGeometry.FILENAME)

        if not os.path.exists(file_name):
            raise XMLBadFileError("Cannot read default dom geometry file"
                                  " \"%s\"" % file_name)

        try:
            dom = minidom.parse(file_name)
        except Exception as exc:
            raise XMLFormatError("Couldn't parse \"%s\": %s" %
                                 (file_name, str(exc)))

        g_list = dom.getElementsByTagName("domGeometry")
        if g_list is None or len(g_list) != 1:
            raise XMLFormatError("No <domGeometry> tag found in %s" %
                                 file_name)

        geom = DefaultDomGeometry(translate_doms)
        for kid in g_list[0].childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "string":
                    cls.__parse_string_node(geom, kid)
                else:
                    raise XMLFormatError("Unknown domGeometry node <%s>" %
                                         kid.nodeName)
                continue

            raise XMLFormatError("Found unknown domGeometry node <%s>" %
                                 kid.nodeName)

        # clean up XML objects
        dom.unlink()

        return geom


class DomsTxtReader(object):
    "Read Mark Krasberg's doms.txt file"

    @staticmethod
    def parse(file_name=None, def_dom_geom=None):
        "Parse a doms.txt file"
        if file_name is None:
            config_dir = find_pdaq_config()
            file_name = os.path.join(config_dir, "doms.txt")

        if not os.path.exists(file_name):
            raise XMLBadFileError("Cannot read doms.txt file \"%s\"" %
                                  file_name)

        with open(file_name, 'r') as fin:
            new_geom = def_dom_geom is None
            if new_geom:
                def_dom_geom = DefaultDomGeometry()

            for line in fin:
                line = line.rstrip()
                if line == "":
                    continue

                (loc, prod_id, name, mbid) = re.split(r"\s+", line, 3)
                if mbid == "mbid":
                    continue

                try:
                    (str_str, pos_str) = re.split("-", loc)
                    str_num = int(str_str)
                    pos = int(pos_str)
                except ValueError:
                    print("Bad location \"%s\" for DOM \"%s\"" %
                          (loc, prod_id), file=sys.stderr)
                    continue

                if pos is None or pos <= 60:
                    orig_str = None
                elif pos <= 64:
                    orig_str = str_num
                    str_num = DefaultDomGeometry.get_icetop_string(orig_str)
                elif pos <= 66:
                    orig_str = str_num
                    str_num \
                      = DefaultDomGeometry.get_scintillator_string(orig_str)
                elif str_num == 0 and 90 <= pos < 100:
                    # ignore ancient Amanda DOMs
                    pass
                else:
                    raise XMLFormatError("Bad position %s in line \"%s\"" %
                                         (pos, line))
                def_dom_geom.add_string(str_num, error_on_multi=False)

                if new_geom:
                    dom = None
                else:
                    dom = def_dom_geom.get_dom(str_num, pos, prod_id)

                if dom is None:
                    dom = DomGeometry(str_num, pos, mbid, name, prod_id)
                    dom.validate()

                    def_dom_geom.add_dom(dom)

                if orig_str is not None:
                    if dom.original_string is None or \
                            dom.original_string != orig_str:
                        dom.original_string = orig_str

        return def_dom_geom


class NicknameReader(object):
    "Read Mark Krasberg's nicknames.txt file"

    SPECIAL_STRINGS = ["SP", "1C"]

    @classmethod
    def parse(cls, file_name=None, def_dom_geom=None):
        if file_name is None:
            config_dir = find_pdaq_config()
            file_name = os.path.join(config_dir, "nicknames.txt")

        if not os.path.exists(file_name):
            raise XMLBadFileError("Cannot read nicknames file \"%s\"" %
                                  file_name)

        with open(file_name, 'r') as fin:
            new_geom = def_dom_geom is None
            if new_geom:
                def_dom_geom = DefaultDomGeometry()

            for line in fin:
                line = line.rstrip()
                if line == "":
                    continue

                flds = re.split(r"\s+", line, 4)
                if len(flds) == 5:
                    (mbid, prod_id, name, loc, desc) = flds
                elif len(flds) == 4:
                    (mbid, prod_id, name, loc) = flds
                    desc = None
                else:
                    print("Missing location for \"%s\"" % (line, ),
                          file=sys.stderr)
                    continue

                if mbid == "mbid":
                    continue

                if loc == "-":
                    str_num = None
                    pos = None
                else:
                    flds = loc.split("-", 1)
                    if len(flds) != 2:
                        raise XMLFormatError("Bad location \"%s\""
                                             " in line \"%s\"" %
                                             (loc, line))

                    if flds[0] in cls.SPECIAL_STRINGS:
                        str_num = flds[0]
                    else:
                        try:
                            str_num = int(flds[0])
                        except ValueError:
                            print("Bad string number \"%s\" in line \"%s\"" %
                                  (flds[0], line), file=sys.stderr)
                            continue

                    try:
                        pos = int(flds[1])
                    except:
                        raise XMLFormatError("Bad DOM position number \"%s\""
                                             " in line \"%s\"" %
                                             (flds[1], line))

                if pos is None or pos <= 60:
                    orig_str = None
                elif pos <= 64:
                    orig_str = str_num
                    str_num = DefaultDomGeometry.get_icetop_string(orig_str)
                elif pos <= 66:
                    orig_str = str_num
                    str_num \
                      = DefaultDomGeometry.get_scintillator_string(orig_str)
                elif str_num == 0 and 90 <= pos < 100:
                    # ignore ancient Amanda DOMs
                    pass
                else:
                    raise XMLFormatError("Bad position %s in line \"%s\"" %
                                         (pos, line))

                def_dom_geom.add_string(str_num, error_on_multi=False)

                if new_geom:
                    dom = None
                else:
                    dom = def_dom_geom.get_dom(str_num, pos, prod_id)

                if dom is not None:
                    if desc != "-":
                        dom.description = desc
                else:
                    dom = DomGeometry(str_num, pos, mbid, name, prod_id)
                    dom.validate()

                    def_dom_geom.add_dom(dom)

                if orig_str is not None:
                    if dom.original_string is None or \
                            dom.original_string != orig_str:
                        dom.original_string = orig_str

        return def_dom_geom


class GeometryFileReader(object):
    """Read IceCube geometry settings (from "Geometry releases" wiki page)"""

    @staticmethod
    def parse(file_name=None, def_dom_geom=None, min_coord_diff=0.000001):
        "Parse text file containing IceCube geometry settings"

        if file_name is None:
            raise XMLBadFileError("No geometry file specified")

        if not os.path.exists(file_name):
            raise XMLBadFileError("Cannot read geometry file \"%s\"" %
                                  file_name)

        with open(file_name, 'r') as fin:
            new_geom = def_dom_geom is None
            if new_geom:
                def_dom_geom = DefaultDomGeometry()

            line_pat = re.compile(r"^\s*(\d+)\s+(\d+)\s+(-*\d+\.\d+)" +
                                  r"\s+(-*\d+\.\d+)\s+(-*\d+\.\d+)\s*$")

            linenum = 0
            for line in fin:
                line = line.rstrip()
                linenum += 1

                if line == "":
                    continue

                mtch = line_pat.match(line)
                if mtch is None:
                    print("Bad geometry line %d: %s" % (linenum, line),
                          file=sys.stderr)
                    continue

                str_str = mtch.group(1)
                pos_str = mtch.group(2)
                x_str = mtch.group(3)
                y_str = mtch.group(4)
                z_str = mtch.group(5)

                try:
                    str_num = int(str_str)
                except ValueError:
                    print("Bad string \"%s\" on line %d" %
                          (str_str, linenum), file=sys.stderr)
                    continue

                try:
                    pos = int(pos_str)
                except ValueError:
                    print("Bad position \"%s\" on line %d" %
                          (pos_str, linenum), file=sys.stderr)
                    continue

                (x_coord, y_coord, z_coord) = (None, None, None)

                for cstr in (x_str, y_str, z_str):
                    try:
                        val = float(cstr)
                    except ValueError:
                        print("Bad coordinate \"%s\" on line %d" %
                              (cstr, linenum), file=sys.stderr)
                        break

                    if x_coord is None:
                        x_coord = val
                    elif y_coord is None:
                        y_coord = val
                    elif z_coord is None:
                        z_coord = val
                    else:
                        print("Too many coordinates on line %d" % linenum,
                              file=sys.stderr)
                        break

                if pos is None or pos <= 60:
                    orig_str = None
                elif pos <= 64:
                    orig_str = str_num
                    str_num = DefaultDomGeometry.get_icetop_string(orig_str)
                elif pos <= 66:
                    orig_str = str_num
                    str_num \
                      = DefaultDomGeometry.get_scintillator_string(orig_str)
                elif str_num == 0 and 90 <= pos < 100:
                    # ignore ancient Amanda DOMs
                    pass
                else:
                    raise XMLFormatError("Bad position %s in line \"%s\"" %
                                         (pos, line))

                def_dom_geom.add_string(str_num, error_on_multi=False)

                if new_geom:
                    dom = None
                else:
                    dom = def_dom_geom.get_dom(str_num, pos, orig_num=orig_str)

                if dom is None:
                    dom = DomGeometry(str_num, pos, None, None, None)

                    def_dom_geom.add_dom(dom)

                if orig_str is not None:
                    if dom.original_string is None or \
                            dom.original_string != orig_str:
                        dom.original_string = orig_str

                if dom.x_coord() is None or \
                   (min_coord_diff is not None and
                    abs(dom.x_coord() - x_coord) > min_coord_diff):
                    dom.x_coord = x_coord
                if y_coord is not None:
                    if dom.y_coord() is None or \
                       (min_coord_diff is not None and
                        abs(dom.y_coord() - y_coord) > min_coord_diff):
                        dom.y_coord = y_coord
                if z_coord is not None:
                    if dom.z_coord() is None or \
                       (min_coord_diff is not None and
                        abs(dom.z_coord() - z_coord) > min_coord_diff):
                        dom.z_coord = z_coord

        return def_dom_geom


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", dest="input_file",
                        help="Name of input file")
    parser.add_argument("-o", "--output", dest="output_file",
                        help="Name of file where new geometry will be written")

    args = parser.parse_args()

    # read in default-dom-geometry.xml
    def_dom_geom = DefaultDomGeometryReader.parse(file_name=args.input_file)

    # validate everything
    def_dom_geom.validate()

    # dump the new default-dom-geometry data
    if args.output_file is not None:
        with open(args.output_file, "w") as fout:
            def_dom_geom.dump(fout)


if __name__ == "__main__":
    main()
