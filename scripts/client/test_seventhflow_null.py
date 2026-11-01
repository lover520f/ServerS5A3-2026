"""Bounded Seventh Flow machine-code regression; never starts the game.

Runs the original complete initializer, its real skill-cache getter, and the
actual NULL -> level getter -> codec fault chain. Scene/type lookup, base
initialization, skill catalog, global locks/flags, valid-skill arithmetic and
encoded result storage are explicit adapters. This does not emulate rendering,
network ownership or an entire multiplayer client.
"""
import argparse
import json
from pathlib import Path
import struct

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn.x86_const import *
import patch_seventhflow_null as patch


class Native:
    OBJECT, OWNER, SKILL = 0x20000000, 0x20010000, 0x20020000
    STUB, STACK, RETURN = 0x21000000, 0x22008000, 0x21000F00
    REGISTERS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
                 UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                 UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS)

    def __init__(self, data, code, state, alignment, page=0):
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        opt, sections = patch.pe.headers(data)
        self.u.mem_map(patch.pe.IMAGE_BASE, struct.unpack_from('<I', data, opt + 56)[0])
        for va, size, raw in sections:
            if size:
                self.u.mem_write(va, data[raw:raw + size])
        for va, size in ((self.OBJECT, 0x40000), (self.STUB, 0x1000), (0x22000000, 0x10000)):
            self.u.mem_map(va, size)
        # Only the native getter needs the isolated x86 SEH head. Unmap page
        # zero as soon as it returns, before any dereference under test.
        self.u.mem_map(0, 0x1000)
        self.put(0, 0xABCDE000)
        self.u.mem_write(self.RETURN, b'\xCC')
        self.object = self.OBJECT + alignment
        self.state, self.page = state, page
        self.effects, self.faults, self.visited = [], [], set()
        self.resume, self.finished = None, False
        self.put(self.object, 0x04AAC7BC)  # Exact Seventh Flow vtable.
        self.put(self.object + 0x14A4, code)
        self.put(self.OWNER, 0x04B54C6C)  # Exact character skill getter vtable.
        self.put(self.OWNER + 0x4088, 16 if state == 'excluded_job' else 1)
        self.put(self.OWNER + 0x5D74, 3 if state == 'invalid_page' else page)
        if state == 'valid':
            self.put(self.OWNER + 0x4D74 + 2048 * page + 130 * 4, self.SKILL)
        self.hooks = {
            0x2C86660: self.base_init,
            0x2694190: lambda: self.ret(value=self.OWNER),
            0x3E73CB6: lambda: self.ret(value=0 if state == 'missing_owner' else self.OWNER),
            0x295AD90: self.catalog,
            0x37E3940: lambda: self.ret(),
            0x37E3970: lambda: self.ret(),
            0x37DF710: lambda: self.ret(8),
            0x2947D20: self.calculate,
            0x142ADB0: lambda: self.ret(value=self.OWNER),
            0x1424520: lambda: self.ret(value=0),
            0x1FA2790: lambda: self.ret(value=self.OWNER),
            0x2047360: lambda: self.ret(value=self.OWNER),
            0x2046D70: lambda: self.ret(4, 0),
        }
        for ea in (0x37DF130, 0x37DF1B0, 0x37DF230, 0x37DF2B0, 0x37DF010):
            self.hooks[ea] = self.store_result
        self.u.hook_add(UC_HOOK_CODE, self.hook)
        self.u.hook_add(UC_HOOK_MEM_INVALID, self.bad_memory)

    def put(self, at, value):
        self.u.mem_write(at, struct.pack('<I', value))

    def read(self, at):
        return struct.unpack('<I', self.u.mem_read(at, 4))[0]

    def reg(self, register):
        return self.u.reg_read(register)

    def arg(self, index=0):
        return self.read(self.reg(UC_X86_REG_ESP) + 4 + index * 4)

    def ret(self, pop=0, value=None):
        sp = self.reg(UC_X86_REG_ESP)
        if value is not None:
            self.u.reg_write(UC_X86_REG_EAX, value)
        self.u.reg_write(UC_X86_REG_EIP, self.read(sp))
        self.u.reg_write(UC_X86_REG_ESP, sp + 4 + pop)

    def base_init(self):
        self.effects.append(['base', self.arg()])
        self.ret(4)

    def catalog(self):
        self.effects.append(['catalog', self.arg(), self.arg(1)])
        self.ret(value=0)  # cdecl; native caller removes both arguments.

    def calculate(self):
        if self.reg(UC_X86_REG_ECX) == 0:
            return  # Run the real broken chain; the fault must not be mocked.
        assert self.reg(UC_X86_REG_ECX) == self.SKILL
        args = [self.arg(i) for i in range(5)]
        self.effects.append(['calculate', args])
        assert args == [0 if self.read(self.object + 0x14A4) == 38801 else 1,
                        0x3F800000, 0xFFFFFFFF, 0, 0xFFFFFFFF]
        self.ret(20, 700 + args[0])

    def store_result(self):
        self.effects.append(['store', self.reg(UC_X86_REG_EIP), self.read(self.arg()), self.arg(1)])
        assert self.arg(1) == self.object + 0x508 + 44
        self.ret(8, 0x12345678)

    def bad_memory(self, _u, access, address, size, _value, _context):
        self.faults.append(dict(ip=hex(self.reg(UC_X86_REG_EIP)), address=hex(address), size=size))
        return False

    def hook(self, _u, at, _size, _context):
        self.visited.add(at)
        if at == patch.SITE:
            assert self.read(0) == 0xABCDE000, 'native skill getter must restore SEH'
            self.u.mem_unmap(0, 0x1000)
        if at == patch.CONTINUE:
            self.resume = [self.reg(r) for r in self.REGISTERS]
        if at == self.RETURN:
            self.finished = True
            self.u.emu_stop()
        elif at in self.hooks:
            self.hooks[at]()

    def run(self):
        saved = [(UC_X86_REG_EBX, 0xBADF00D), (UC_X86_REG_ESI, 0xCAFE0100),
                 (UC_X86_REG_EDI, 0xCAFE0200), (UC_X86_REG_EBP, 0xCAFE0300)]
        for reg, value in saved + [(UC_X86_REG_ESP, self.STACK),
                                   (UC_X86_REG_ECX, self.object), (UC_X86_REG_EFLAGS, 0x246)]:
            self.u.reg_write(reg, value)
        self.put(self.STACK, self.RETURN)
        self.put(self.STACK + 4, 0x11223344)
        try:
            self.u.emu_start(0x2C8A690, 0xFFFFFFFF, count=5000)
        except UcError:
            if not self.faults:
                raise
        if self.finished:
            assert not self.faults
            assert self.reg(UC_X86_REG_ESP) == self.STACK + 8
            assert all(self.reg(r) == v for r, v in saved), 'callee-saved registers'
        else:
            assert self.faults, 'instruction budget exhausted'
        if self.state != 'missing_owner':
            assert 0x2773700 in self.visited, 'real skill cache getter not run'
        return dict(finished=self.finished, faults=self.faults, effects=self.effects,
                    resume=self.resume, registers=[self.reg(r) for r in self.REGISTERS])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    original = args.input.read_bytes()
    candidate, receipt = patch.build(original)
    cases = []
    for code in (38801, 38802):
        for alignment in (0, 4, 8, 12, 1):
            for state in ('missing_catalog', 'excluded_job', 'invalid_page', 'missing_owner', 'valid'):
                page = alignment % 3
                old = Native(original, code, state, alignment, page).run()
                new = Native(candidate, code, state, alignment, page).run()
                assert new['finished']
                if state in ('valid', 'missing_owner'):
                    assert old == new, (code, state, alignment, old, new)
                else:
                    assert old['faults'] == [{'ip': '0x37df6a3', 'address': '0xf9c', 'size': 4}]
                    assert old['effects'] == new['effects']
                    assert not any(e[0] in ('calculate', 'store') for e in new['effects'])
                cases.append(dict(code=code, state=state, alignment=alignment, page=page,
                                  oldFaults=old['faults'], passed=True))
    for invalid in (original[:-1], bytes([original[0] ^ 1]) + original[1:], candidate):
        try:
            patch.build(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid or already patched input accepted')
    args.report.write_text(json.dumps(dict(cases=cases, passed=len(cases), rejectedInputs=3,
                                          candidate=receipt, gameAcceptance='pending'), indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=len(cases), rejectedInputs=3, outputSha256=receipt['outputSha256'])))


if __name__ == '__main__':
    main()
