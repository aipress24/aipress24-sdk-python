# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""CAR files: the content of an AT Protocol (Bluesky) repository.

See https://atproto.com/specs/repository and https://dag-cbor.ipld.io.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

_CID_TAG = 42
_SHA256 = b"\x12\x20"
_SIMPLE = {20: False, 21: True, 22: None}


class Cid(bytes):
    """The identifier of a block, which is its digest."""

    def __str__(self) -> str:
        return "b" + base64.b32encode(self).decode().lower().rstrip("=")


def read_records(path: Path) -> tuple[str, dict[str, Any]]:
    """Return the account, and its records by path."""
    data = path.read_bytes()
    length, start = _varint(data, 0)
    header, _ = decode(data[start : start + length])
    blocks = dict(_blocks(data, start + length))
    commit, _ = decode(blocks[header["roots"][0]])
    records = {
        key: decode(blocks[cid])[0] for key, cid in _walk(blocks, commit["data"])
    }
    return commit["did"], records


def _blocks(data: bytes, position: int) -> Iterator[tuple[Cid, bytes]]:
    while position < len(data):
        length, start = _varint(data, position)
        position = start + length
        if position > len(data):
            msg = "the file is truncated"
            raise ValueError(msg)
        # A version 1 identifier: version, codec, then a multihash.
        _, hash_start = _varint(data, start)
        _, hash_start = _varint(data, hash_start)
        end = hash_start + len(_SHA256) + 32
        digest = data[hash_start:end]
        content = data[end:position]
        if digest != _SHA256 + hashlib.sha256(content).digest():
            msg = "a block does not match its digest"
            raise ValueError(msg)
        yield Cid(data[start:end]), content


def _walk(blocks: Mapping[Cid, bytes], cid: Cid) -> Iterator[tuple[str, Cid]]:
    """The entries of a Merkle search tree, in order."""
    node, _ = decode(blocks[cid])
    if node["l"]:
        yield from _walk(blocks, node["l"])
    key = b""
    for entry in node["e"]:
        key = key[: entry["p"]] + entry["k"]
        yield key.decode(), entry["v"]
        if entry["t"]:
            yield from _walk(blocks, entry["t"])


def _varint(data: bytes, position: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, position


def decode(data: bytes, position: int = 0) -> tuple[Any, int]:
    """Decode a DAG-CBOR value; return it with the position after it."""
    major, info = data[position] >> 5, data[position] & 0x1F
    position += 1
    if major == 7:
        if info == 27:
            end = position + 8
            return struct.unpack(">d", data[position:end])[0], end
        return _SIMPLE[info], position
    if info >= 28:
        msg = "indefinite lengths are not allowed"
        raise ValueError(msg)
    number = info
    if info >= 24:
        end = position + (1 << (info - 24))
        number, position = int.from_bytes(data[position:end], "big"), end
    match major:
        case 0:
            return number, position
        case 1:
            return -1 - number, position
        case 2:
            return data[position : position + number], position + number
        case 3:
            end = position + number
            return data[position:end].decode(), end
        case 4:
            return _decode_list(data, position, number)
        case 5:
            items, position = _decode_list(data, position, 2 * number)
            return dict(zip(items[::2], items[1::2], strict=True)), position
        case _:
            value, position = decode(data, position)
            # An identifier is prefixed with a null byte.
            return Cid(value[1:]) if number == _CID_TAG else value, position


def _decode_list(data: bytes, position: int, length: int) -> tuple[list[Any], int]:
    items = []
    for _ in range(length):
        item, position = decode(data, position)
        items.append(item)
    return items, position
