"""Guard a missing Seventh Flow skill during passive-object initialization.

Produces a separate candidate. Does not launch the game or publish an update.
"""
import argparse
import json
from pathlib import Path
import struct

import patch_receivers_v128 as pe
from patch_at5t_input_priority import Code

INPUTS = {
    'b965e2d1d04b4679eba1ba00de6bbceacdc1ccab8789ea22bef98a28f61283d5': 112123904,
    '534b5ef166d0090d1ab88e01f5f443721abf97eabfacfb007e04e30fd9d51b24': 112541696,
}
SITE = 0x02C8A6DE
ORIGINAL = bytes.fromhex('8b16 8bf8 8b424c')
CONTINUE = SITE + len(ORIGINAL)
MISSING = 0x02C8A7C0


def helper(base):
    c = Code(base)
    c.emit('9c 85c0')  # Preserve flags from the skill getter.
    c.branch('0f84', 'missing')
    c.emit('9d')
    c.emit(ORIGINAL.hex())
    c.branch('e9', CONTINUE)
    c.label('missing')
    c.emit('9d')
    c.branch('e9', MISSING)  # Existing pop EDI/ESI/EBP; ret 4.
    return c.finish()


def build(data):
    input_sha = pe.sha(data)
    if INPUTS.get(input_sha) != len(data):
        raise ValueError('exact verified cumulative input SHA256/size required')
    opt, sections = pe.headers(data)
    coff = opt - 24
    count = struct.unpack_from('<H', data, coff + 6)[0]
    table = opt + struct.unpack_from('<H', data, coff + 20)[0]
    header = table + count * 40
    if header + 40 > struct.unpack_from('<I', data, opt + 60)[0] or any(data[header:header + 40]):
        raise ValueError('no empty section header')
    if struct.unpack_from('<II', data, opt + 32) != (4096, 4096) or any(struct.unpack_from('<II', data, opt + 128)):
        raise ValueError('unexpected alignment or certificate')
    image_size = struct.unpack_from('<I', data, opt + 56)[0]
    end = max(struct.unpack_from('<I', data, table + i * 40 + 12)[0] +
              max(struct.unpack_from('<I', data, table + i * 40 + 8)[0],
                  struct.unpack_from('<I', data, table + i * 40 + 16)[0]) for i in range(count))
    if image_size != (end + 4095) & ~4095 or len(data) % 4096 or max(raw + size for _, size, raw in sections) != len(data):
        raise ValueError('unexpected image end or overlay')
    at = pe.offset(sections, SITE, len(ORIGINAL))
    if data[at:at + len(ORIGINAL)] != ORIGINAL:
        raise ValueError('native fingerprint changed')
    for va, expected in (
        (0x02C8A6CA, bytes.fromhex('8b10 57 6a01 8bc8 8b82dc0b0000 6882000000 ffd0')),
        (MISSING, bytes.fromhex('5f5e5dc20400')),
        (0x04AACB18, struct.pack('<I', 0x02C8A690)),
    ):
        off = pe.offset(sections, va, len(expected))
        if data[off:off + len(expected)] != expected:
            raise ValueError('Seventh Flow initializer fingerprint changed')
    base = pe.IMAGE_BASE + image_size
    code = helper(base)
    out = bytearray(data) + code + bytes(4096 - len(code))
    out[at:at + len(ORIGINAL)] = b'\xe9' + struct.pack('<i', base - SITE - 5) + b'\x90' * (len(ORIGINAL) - 5)
    struct.pack_into('<8sIIIIIIHHI', out, header, b'.sfnull', len(code), image_size, 4096, len(data), 0, 0, 0, 0, 0x60000020)
    struct.pack_into('<H', out, coff + 6, count + 1)
    struct.pack_into('<I', out, opt + 4, struct.unpack_from('<I', data, opt + 4)[0] + 4096)
    struct.pack_into('<I', out, opt + 56, image_size + 4096)
    struct.pack_into('<I', out, opt + 64, pe.checksum(out, opt + 64))
    changes = sorted([(at, at + len(ORIGINAL)), (coff + 6, coff + 8), (opt + 4, opt + 8),
                      (opt + 56, opt + 60), (opt + 64, opt + 68), (header, header + 40)])
    normalized = bytearray(out[:len(data)])
    for lo, hi in changes:
        normalized[lo:hi] = data[lo:hi]
    if normalized != data:
        raise ValueError('change outside approved ranges')
    return bytes(out), dict(inputSha256=input_sha, outputSha256=pe.sha(out), size=len(out),
                           helperVA=hex(base), helperSize=len(code), changedRanges=changes,
                           appendedRange=[len(data), len(out)], playerAcceptance='pending')


def write_candidate(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError('output must be a separate new file')
    result, receipt = build(source.read_bytes())
    with destination.open('xb') as stream:
        stream.write(result)
    if pe.sha(source.read_bytes()) != receipt['inputSha256'] or pe.sha(destination.read_bytes()) != receipt['outputSha256']:
        raise RuntimeError('input/output readback mismatch')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(write_candidate(a.input, a.output), indent=2))
