#!/usr/bin/env python

import os
import sys
import traceback

def exc_string():
    '''
    Returns a single line and human readable string containing an exception's
    name and relevant traceback information.
    This is essentially a simplified version of recipe 444746 found on
    code.activestate.com except this one will attempt to fall back to a more
    traditional traceback string in case the intended formatting fails.
    Usage example:
    try:
        1/0
    except:
        print(exc_string())
    '''
    t, v, tb = sys.exc_info()

    try:
        if t is None:
            return 'no exception'
        if v is not None:
            v_display = str(v)
        else:
            v_display = str(t)
        if hasattr(t, '__name__'):
            t_display = t.__name__
        else:
            t_display = type(t).__name__
        tb_list = traceback.extract_tb(tb) or traceback.extract_stack()[:-1]
        tb_str_list = []
        for xfile, line, fct, _ in reversed(tb_list):
            fname = os.path.split(xfile)[1]
            tb_str_list.append('%s() (%s:%s)' % (fct, fname, line))
        tb_display = ' <- '.join(tb_str_list)

        return '%s("%s") in %s' % (t_display, v_display, tb_display)
    except:
        # fallback: return equivalent of traceback.format_exc() in order not to
        # lose the initial exception
        return ''.join(traceback.format_exception(t, v, tb))


def set_exc_string_encoding(charset):
    pass


if __name__ == "__main__":
    try:
        1/0
    except:
        print(exc_string())
