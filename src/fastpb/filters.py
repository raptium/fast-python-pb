def parent_pkg(s):
    """Get the parent package

    >>> parent_pkg('a.b')
    'a'

    >>> parent_pkg('a.b.c.d')
    'a.b.c'

    >>> parent_pkg('a')
    ''

    :param s:
    :return:
    """
    return '.'.join(s.split('.')[:-1])


def proto_name(s):
    """Return the name of the proto file

    >>> proto_name('foo.proto')
    'foo'

    :param s:
    :return:
    """
    return s.split('.')[0]
