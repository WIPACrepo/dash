#!/usr/bin/env python

from __future__ import print_function


class ColorException(Exception):
    "Base exception for this code"
    pass


def escape_string(code):
    "Return a string for the specified ANSI escape code"
    if code <= 0:
        substr = ""
    else:
        substr = str(code)
    return "\033[%sm" % substr


def background_color(color):
    "Return an ANSI string to set the terminal's background color"
    if color < 0 or color > 9:
        raise ColorException("Color must be between 0 and 9, not " + color)
    return escape_string(color + 40)


def foreground_color(color):
    "Return an ANSI string to set the terminal's foreground color"
    if color < 0 or color > 9:
        raise ColorException("Color must be between 0 and 9, not " + color)
    return escape_string(color + 30)


class ANSIEscapeCode(object):
    "Friendly interface for ANSI terminal escape codes"
    OFF = escape_string(0)

    BLACK = 0
    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7
    DEFAULT = 9

    BOLD_ON = escape_string(1)
    ITALIC_ON = escape_string(3)
    UNDERLINE_ON = escape_string(4)
    INVERTED_ON = escape_string(7)
    BOLD_OFF = escape_string(21)
    BOLD_FAINT_OFF = escape_string(22)
    ITALIC_OFF = escape_string(23)
    UNDERLINE_OFF = escape_string(24)
    INVERTED_OFF = escape_string(27)

    FG_BLACK = foreground_color(BLACK)
    FG_RED = foreground_color(RED)
    FG_GREEN = foreground_color(GREEN)
    FG_YELLOW = foreground_color(YELLOW)
    FG_BLUE = foreground_color(BLUE)
    FG_MAGENTA = foreground_color(MAGENTA)
    FG_CYAN = foreground_color(CYAN)
    FG_WHITE = foreground_color(WHITE)
    FG_DEFAULT = foreground_color(DEFAULT)

    BG_BLACK = background_color(BLACK)
    BG_RED = background_color(RED)
    BG_GREEN = background_color(GREEN)
    BG_YELLOW = background_color(YELLOW)
    BG_BLUE = background_color(BLUE)
    BG_MAGENTA = background_color(MAGENTA)
    BG_CYAN = background_color(CYAN)
    BG_WHITE = background_color(WHITE)
    BG_DEFAULT = background_color(DEFAULT)


def main():
    "Main program"
    import sys

    color = 0
    space = ""
    for arg in sys.argv[1:]:
        if color == 0:
            style = ANSIEscapeCode.BOLD_ON
            fg_color = ANSIEscapeCode.FG_BLACK
            bg_color = ANSIEscapeCode.BG_BLUE
        elif color == 1:
            style = ANSIEscapeCode.ITALIC_ON
            fg_color = ANSIEscapeCode.FG_RED
            bg_color = ANSIEscapeCode.BG_MAGENTA
        elif color == 2:
            style = ANSIEscapeCode.UNDERLINE_ON
            fg_color = ANSIEscapeCode.FG_GREEN
            bg_color = ANSIEscapeCode.BG_CYAN
        elif color == 3:
            style = ANSIEscapeCode.INVERTED_ON
            fg_color = ANSIEscapeCode.FG_YELLOW
            bg_color = ANSIEscapeCode.BG_GREEN
        elif color == 4:
            style = ANSIEscapeCode.BOLD_OFF
            fg_color = ANSIEscapeCode.FG_BLUE
            bg_color = ANSIEscapeCode.BG_BLACK
        elif color == 5:
            style = ANSIEscapeCode.ITALIC_OFF
            fg_color = ANSIEscapeCode.FG_MAGENTA
            bg_color = ANSIEscapeCode.BG_RED
        elif color == 6:
            style = ANSIEscapeCode.UNDERLINE_OFF
            fg_color = ANSIEscapeCode.FG_CYAN
            bg_color = ANSIEscapeCode.BG_GREEN
        else:
            style = ANSIEscapeCode.INVERTED_OFF
            fg_color = ANSIEscapeCode.FG_GREEN
            bg_color = ANSIEscapeCode.BG_YELLOW

        print(ANSIEscapeCode.BG_WHITE + space + style + fg_color + bg_color +
              arg, end=' ')
        color = (color + 1) % 8
        space = " "

    print(ANSIEscapeCode.OFF)


if __name__ == "__main__":
    main()
