# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: RequestMsg.proto

import sys
_b=sys.version_info[0]<3 and (lambda x:x) or (lambda x:x.encode('latin1'))
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database
from google.protobuf import descriptor_pb2
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor.FileDescriptor(
  name='RequestMsg.proto',
  package='schemas',
  serialized_pb=_b('\n\x10RequestMsg.proto\x12\x07schemas\"]\n\x0cRequestProto\x12\r\n\x05msgId\x18\x01 \x02(\t\x12\x0f\n\x07version\x18\x02 \x02(\x05\x12\x0e\n\x06hostId\x18\x03 \x02(\t\x12\x0c\n\x04type\x18\x04 \x02(\x05\x12\x0f\n\x07payload\x18\x05 \x01(\t\"s\n\x10RequestRespProto\x12\r\n\x05msgId\x18\x01 \x02(\t\x12\x0f\n\x07version\x18\x02 \x02(\x05\x12\x0e\n\x06hostId\x18\x03 \x02(\t\x12\x10\n\x08reqestId\x18\x04 \x02(\t\x12\x0c\n\x04type\x18\x05 \x02(\x05\x12\x0f\n\x07payload\x18\x06 \x01(\tB#\n!com.segmetics.ng.protocol.message')
)
_sym_db.RegisterFileDescriptor(DESCRIPTOR)




_REQUESTPROTO = _descriptor.Descriptor(
  name='RequestProto',
  full_name='schemas.RequestProto',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  fields=[
    _descriptor.FieldDescriptor(
      name='msgId', full_name='schemas.RequestProto.msgId', index=0,
      number=1, type=9, cpp_type=9, label=2,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='version', full_name='schemas.RequestProto.version', index=1,
      number=2, type=5, cpp_type=1, label=2,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='hostId', full_name='schemas.RequestProto.hostId', index=2,
      number=3, type=9, cpp_type=9, label=2,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='type', full_name='schemas.RequestProto.type', index=3,
      number=4, type=5, cpp_type=1, label=2,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='payload', full_name='schemas.RequestProto.payload', index=4,
      number=5, type=9, cpp_type=9, label=1,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  options=None,
  is_extendable=False,
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=29,
  serialized_end=122,
)


_REQUESTRESPPROTO = _descriptor.Descriptor(
  name='RequestRespProto',
  full_name='schemas.RequestRespProto',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  fields=[
    _descriptor.FieldDescriptor(
      name='msgId', full_name='schemas.RequestRespProto.msgId', index=0,
      number=1, type=9, cpp_type=9, label=2,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='version', full_name='schemas.RequestRespProto.version', index=1,
      number=2, type=5, cpp_type=1, label=2,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='hostId', full_name='schemas.RequestRespProto.hostId', index=2,
      number=3, type=9, cpp_type=9, label=2,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='reqestId', full_name='schemas.RequestRespProto.reqestId', index=3,
      number=4, type=9, cpp_type=9, label=2,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='type', full_name='schemas.RequestRespProto.type', index=4,
      number=5, type=5, cpp_type=1, label=2,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='payload', full_name='schemas.RequestRespProto.payload', index=5,
      number=6, type=9, cpp_type=9, label=1,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  options=None,
  is_extendable=False,
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=124,
  serialized_end=239,
)

DESCRIPTOR.message_types_by_name['RequestProto'] = _REQUESTPROTO
DESCRIPTOR.message_types_by_name['RequestRespProto'] = _REQUESTRESPPROTO

RequestProto = _reflection.GeneratedProtocolMessageType('RequestProto', (_message.Message,), dict(
  DESCRIPTOR = _REQUESTPROTO,
  __module__ = 'RequestMsg_pb2'
  # @@protoc_insertion_point(class_scope:schemas.RequestProto)
  ))
_sym_db.RegisterMessage(RequestProto)

RequestRespProto = _reflection.GeneratedProtocolMessageType('RequestRespProto', (_message.Message,), dict(
  DESCRIPTOR = _REQUESTRESPPROTO,
  __module__ = 'RequestMsg_pb2'
  # @@protoc_insertion_point(class_scope:schemas.RequestRespProto)
  ))
_sym_db.RegisterMessage(RequestRespProto)


DESCRIPTOR.has_options = True
DESCRIPTOR._options = _descriptor._ParseOptions(descriptor_pb2.FileOptions(), _b('\n!com.segmetics.ng.protocol.message'))
# @@protoc_insertion_point(module_scope)
