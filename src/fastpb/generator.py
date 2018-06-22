#!/usr/bin/env python
# Copyright 2011 The fast-python-pb Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Generates a Python wrapper for a C++ protocol buffer."""
import os
import sys

from fastpb import filters
from fastpb.util import order_dependencies
from google.protobuf import descriptor_pb2
from google.protobuf.compiler import plugin_pb2
from jinja2 import Template
from pkg_resources import resource_string

TYPE = {
    'STRING': descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    'DOUBLE': descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE,
    'FLOAT': descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT,
    'INT32': descriptor_pb2.FieldDescriptorProto.TYPE_INT32,
    'SINT32': descriptor_pb2.FieldDescriptorProto.TYPE_SINT32,
    'UINT32': descriptor_pb2.FieldDescriptorProto.TYPE_UINT32,
    'INT64': descriptor_pb2.FieldDescriptorProto.TYPE_INT64,
    'SINT64': descriptor_pb2.FieldDescriptorProto.TYPE_SINT64,
    'UINT64': descriptor_pb2.FieldDescriptorProto.TYPE_UINT64,
    'MESSAGE': descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
    'BYTES': descriptor_pb2.FieldDescriptorProto.TYPE_BYTES,
    'BOOL': descriptor_pb2.FieldDescriptorProto.TYPE_BOOL,
    'ENUM': descriptor_pb2.FieldDescriptorProto.TYPE_ENUM,
    'FIXED32': descriptor_pb2.FieldDescriptorProto.TYPE_FIXED32,
    # TODO(robbyw): More types.
}

LABEL = {
    'REPEATED': descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
}


def template(name):
    """Gets a template of the given name."""
    tmpl = Template(resource_string(__name__, 'template/' + name))

    tmpl.environment.filters['parent_pkg'] = filters.parent_pkg
    tmpl.environment.filters['proto_name'] = filters.proto_name

    return tmpl


def sort_messages(proto_file):
    """Return a sorted list of messages (sub-messages first).

    This avoids compilation problems involving declaration order.
    """
    dependencies = []
    msg_dict = {}

    def visit(base_name, messages, parent=None):
        """Visitor for the message tree."""
        for msg in messages:
            # Build our type name (using the protocol buffer convention) and
            # use it to register this message type object in our dictionary.
            type_name = base_name + '.' + msg.name
            msg_dict[type_name] = msg

            # If this is a nested message type, prepend our parent's name to
            # our name for all future name lookups (via template expansion).
            # This disambiguates nested message names so that two n-level
            # messages can both have nested message types with the same name.
            # This also matches the generated C++ code's naming convention.
            if parent is not None:
                msg.name = parent.name + '_' + msg.name

            # If this message has nested message types, recurse.
            if msg.nested_type:
                visit(type_name, msg.nested_type, parent=msg)

            # Generate the set of messages that this type is dependent upon.
            deps = set([field.type_name for field in msg.field
                        if field.type == TYPE['MESSAGE']])
            dependencies.append((type_name, deps))

    # Start by visiting the file's top-level message types.
    visit('.' + proto_file.package, proto_file.message_type)

    sorted_msg_names = order_dependencies(dependencies)
    return [msg_dict[n] for n in sorted_msg_names if n in msg_dict]


def write_proto_cc(response, proto_file):
    """Writes a C file."""
    messages = sort_messages(proto_file)

    name = os.path.splitext(proto_file.name)[0]

    context = {
        'fileName': name,
        'moduleName': proto_file.package.lstrip('.'),
        'package': proto_file.package.replace('.', '::'),
        'packageName': proto_file.package.split('.')[-1],
        'messages': messages,
        'enums': proto_file.enum_type,
        'dependencies': proto_file.dependency,
        'TYPE': TYPE,
        'LABEL': LABEL,
    }

    cc_file = response.file.add()
    cc_file.name = name + '.cc'
    cc_file.content = template('proto.jinjacc').render(context)

    header_file = response.file.add()
    header_file.name = name + '.h'
    header_file.content = template('proto.jinjah').render(context)


def write_module_cc(response, package):
    """Writes a C file."""

    context = {
        'package': package,
    }

    cc_file = response.file.add()
    cc_file.name = package['name'] + '.cc'
    cc_file.content = template('module.jinjacc').render(context)


def write_setup_py(response, packages):
    """Writes the setup.py file."""

    context = {
        'packages': packages,
        'namespaces': generate_namespaces(packages),
    }

    setup_file = response.file.add()
    setup_file.name = 'setup.py'
    setup_file.content = template('setup.jinjapy').render(context)


def write_tests(response, packages):
    """Writes the tests."""

    content = {
        'packages': packages,
        'TYPE': TYPE,
        'LABEL': LABEL
    }

    test_file = response.file.add()
    test_file.name = 'test.py'
    test_file.content = template('test.jinjapy').render(content)


def write_manifest(response, packages):
    """Writes the manifest."""

    context = {
        'packages': packages,
    }

    manifest_file = response.file.add()
    manifest_file.name = 'MANIFEST.in'
    manifest_file.content = template('MANIFEST.jinjain').render(context)


def generate_namespaces(packages):
    namespaces = set([])

    for pkg in packages:
        components = pkg['name'].split('.')[:-1]
        for i in xrange(len(components)):
            ns = '.'.join(components[i:])
            if ns != '':
                namespaces.add(ns)
    return sorted(namespaces)


def create_namespaces(response, packages):
    for ns in generate_namespaces(packages):
        init_file = response.file.add()
        path_components = ['src']
        path_components.extend(ns.split('.'))
        path_components.append('__init__.py')
        init_file.name = os.path.join(*path_components)
        init_file.content = '''__import__('pkg_resources').declare_namespace(__name__)'''


def main():
    """Main generation method."""
    request = plugin_pb2.CodeGeneratorRequest()
    request.ParseFromString(sys.stdin.read())

    response = plugin_pb2.CodeGeneratorResponse()

    packages = {}

    to_generate = set(request.file_to_generate)

    for proto_file in request.proto_file:

        if proto_file.name not in to_generate:
            continue

        if not proto_file.package:
            sys.stderr.write('%s: package definition required, but not found\n' % proto_file.name)
            sys.exit(1)

        write_proto_cc(response, proto_file)

        package = proto_file.package.lstrip('.')

        if package in packages:
            packages[package].append(proto_file)
        else:
            packages[package] = [proto_file]

    package_list = [{'name': k, 'children': v} for (k, v) in packages.iteritems()]

    # sys.stderr.write('%s' % package_list)

    for package in package_list:
        write_module_cc(response, package)

    write_setup_py(response, package_list)
    write_tests(response, package_list)
    write_manifest(response, package_list)
    create_namespaces(response, package_list)

    sys.stdout.write(response.SerializeToString())


if __name__ == '__main__':
    main()
