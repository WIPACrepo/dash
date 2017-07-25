#!/usr/bin/env python
#
# Parse pDAQ color files (used to specify colors for `pdaq taillive`)

import os

from ANSIEscapeCode import ANSIEscapeCode


class ColorException(Exception):
    pass


class ColorFileParser(object):
    # names of each of the three possible fields
    FIELDNAMES = ("foreground color", "background color", "modifier")

    DEFAULT_FIELD = "DEFAULT"

    COLOR_MAP = {
        "black": ANSIEscapeCode.BLACK,
        "red": ANSIEscapeCode.RED,
        "green": ANSIEscapeCode.GREEN,
        "yellow": ANSIEscapeCode.YELLOW,
        "blue": ANSIEscapeCode.BLUE,
        "magenta": ANSIEscapeCode.MAGENTA,
        "cyan": ANSIEscapeCode.CYAN,
        "white": ANSIEscapeCode.WHITE,
    }

    def __init__(self, filename=None):
        if filename is None:
            if "PDAQ_COLORS" in os.environ:
                filename = os.environ["PDAQ_COLORS"]
            else:
                cpath = os.path.join(os.environ["HOME"], ".pdaq_colors")
                if os.path.exists(cpath):
                    filename = cpath

        self.__filename = filename

    def __fill_in_defaults(self, color_dict):
        """
        Fill in any missing values with the default values
        """

        defaults = self.__fix_defaults(color_dict)

        for fld in color_dict:
            if fld == self.DEFAULT_FIELD:
                continue

            # if no colors are specified, they must want a plain line
            if color_dict[fld] is None or \
               len(color_dict[fld]) == 0:
                continue

            # if they only specified the foreground color,
            #  mark this field's background color as undefined
            if len(color_dict[fld]) == 1:
                color_dict[fld].append(None)

            # if the default value includes modifiers,
            #  mark this field's modifiers as undefined
            if defaults[2] != "" and len(color_dict[fld]) == 2:
                if isinstance(color_dict[fld], tuple):
                    color_dict[fld] = list(color_dict[fld])
                color_dict[fld].append(None)

            # fill in any undefined colors with the default value
            for idx in range(len(color_dict[fld])):
                if color_dict[fld][idx] is None:
                    color_dict[fld][idx] = defaults[idx]

    def __fix_defaults(self, color_dict):
        """
        Make sure default entry is valid and specified all fields
        """
        defaults = list(color_dict[self.DEFAULT_FIELD])
        modified = False

        # complain if a field entry is unspecified
        for idx in range(len(defaults)):
            if defaults[idx] is None:
                if idx == 2:
                    defaults[2] = ""
                    modified = True
                else:
                    raise ColorException("Undefined default for %s in \"%s\"" %
                                         (self.FIELDNAMES[idx],
                                          self.__filename))

        # make sure there are default values for all the fields
        while len(defaults) < len(self.FIELDNAMES):
            defaults.append("")
            modified = True


        if modified:
            color_dict[self.DEFAULT_FIELD] = defaults

        return defaults

    def __parse_colors(self, fldstr):
        # nothing is defined initially
        colors = [None, None, None]

        # parse color definitions
        cflds = fldstr.split("/", 2)
        for cnum in range(len(cflds)):

            # extract next definition
            clow = cflds[cnum].strip().lower()

            # modifier fields
            if cnum == 2:
                color = ""
                for ctmp in clow.split():
                    if ctmp == "bold":
                        color += ANSIEscapeCode.BOLD_ON
                    elif ctmp == "italic":
                        color += ANSIEscapeCode.ITALIC_ON
                    elif ctmp == "underline":
                        color += ANSIEscapeCode.UNDERLINE_ON
                    elif ctmp == "none":
                        color = ""
                    else:
                        raise ColorException("Bad modifier \"%s\"" % (ctmp, ))

                # update modifier entry
                colors[cnum] = color
                break

            if cnum == 0:
                # first field can be a single
                if clow == "skip":
                    colors[cnum] = None
                    break
                elif clow == "none":
                    colors[cnum] = []
                    break

            if clow == "":
                # defer this field until later
                colors[cnum] = None
                continue

            # get the escape code associated with the color name
            try:
                colors[cnum] = self.value(clow)
                continue
            except ColorException, cex:
                raise ColorException("Bad %s in \"%s\" line %d: %s" %
                                     (self.FIELDNAMES[cnum], self.__filename,
                                      linenum, line))
        return colors

    @property
    def filename(self):
        return self.__filename

    @classmethod
    def name(cls, color_value):
        if color_value is None:
            raise ColorException("Value cannot be None")

        for name, val in cls.COLOR_MAP.items():
            if val == color_value:
                return name

        raise ColorException("Unknown color value %s" % (color_value, ))

    def parse(self, predefined):
        if self.__filename is None:
            return

        if not os.path.exists(self.__filename):
            raise ColorException("Bad color file \"%s\"" % (self.__filename, ))

        with open(self.__filename, "r") as fin:
            linenum = 0
            for line in fin:
                linenum += 1

                # lose comments
                pos = line.find("#")
                if pos >= 0:
                    line = line[:pos]

                # trim trailing whitespace
                line = line.rstrip()

                # ignore blank lines
                if line == "":
                    continue

                # separate field name from color definitions
                flds = line.split(":", 1)
                if len(flds) < 2:
                    raise ColorException("No colon in \"%s\" line %d: %s" %
                                         (self.__filename, linenum, line))

                # clean up field name
                name = flds[0].strip().lower()
                if name == "default":
                    name = self.DEFAULT_FIELD

                # parse and assign colors
                predefined[name] = self.__parse_colors(flds[1])

            self.__fill_in_defaults(predefined)

    @classmethod
    def print_formatted(cls, color_dict):
        keys = color_dict.keys()
        keys.sort()
        didx = keys.index(ColorFileParser.DEFAULT_FIELD)
        if didx > 0:
            del keys[didx]
            keys.insert(ColorFileParser.DEFAULT_FIELD, 0)
        elif didx < 0:
            raise ColorException("Dictionary is missing a default entry")

        print "# field: foreground / background / bold italic underline"
        print "# can also specify \"none\" for no colors" \
            " or \"skip\" to not print the line"
        print

        defaults = color_dict[ColorFileParser.DEFAULT_FIELD]
        for fld in keys:
            colors = color_dict[fld]

            is_dflt = fld == ColorFileParser.DEFAULT_FIELD

            if colors is None:
                fstr = "skip"
            elif len(colors) == 0:
                fstr = "none"
            else:
                if len(colors) != len(defaults):
                    same = False
                else:
                    same = not is_dflt
                    for idx in range(len(colors)):
                        if colors[idx] != defaults[idx]:
                            same = False

                if same:
                    fstr = None
                else:
                    fg_color = ""
                    bg_color = ""
                    for idx in range(2):
                        if len(colors) <= idx:
                            cstr = ""
                        elif colors[idx] == "":
                            cstr = ""
                        elif not is_dflt and len(defaults) > idx and \
                             colors[idx] == defaults[idx]:
                            cstr = ""
                        else:
                            cstr = cls.name(colors[idx])
                        if idx == 0:
                            fg_color = cstr
                        else:
                            bg_color = cstr

                    modifiers = ""
                    if len(colors) > 2:
                        if not is_dflt and len(defaults) > 2 and \
                           colors[2] == defaults[2]:
                            pass
                        else:
                            pairs = (
                                ("bold", ANSIEscapeCode.BOLD_ON),
                                ("italic", ANSIEscapeCode.ITALIC_ON),
                                ("underline", ANSIEscapeCode.UNDERLINE_ON),
                            )
                            for pair in pairs:
                                if pair[1] in colors[2]:
                                    if modifiers != "":
                                        modifiers += " "
                                    modifiers += pair[0]

                    fstr = ""
                    if bg_color == "" and modifiers == "":
                        fstr = fg_color
                    elif modifiers == "":
                        fstr = fg_color + " / " + bg_color
                    else:
                        fstr = fg_color + " / " + bg_color + " / " + modifiers

            if fstr is None:
                print "# %s: default" % (fld, )
            else:
                print "%s: %s" % (fld, fstr)

            if is_dflt:
                # leave whitespace before and after default
                print

    @classmethod
    def value(cls, color_name):
        if color_name is None:
            raise ColorException("Name cannot be None")

        tmp_name = color_name.strip().lower()
        if tmp_name not in cls.COLOR_MAP:
            raise ColorException("Bad color name \"%s\"" % (color_name, ))

        return cls.COLOR_MAP[tmp_name]


if __name__ == "__main__":
    import sys

    from TailLive import LiveLog

    print "%d args" % len(sys.argv)
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = None

    try:
        ColorFileParser(filename).parse(LiveLog.COLORS)
    except ColorException, cex:
        raise SystemExit(str(cex))

    ColorFileParser.print_formatted(LiveLog.COLORS)
