"""Inspect the ARM64 Mach-O layout used by Terminal.app 2.15 (488.9).

Metadata inspection needs only Python. Optional disassembly uses libLLVM's C API.
This is a research helper for this executable layout, not a general Mach-O parser.
"""

import argparse
import bisect
import ctypes
import ctypes.util
import hashlib
import json
import os
import re
import struct
from pathlib import Path

BASE = 0x100000000

class MachO:
    def __init__(self, data, llvm_library=None, disassembly=False):
        self.data = data if isinstance(data, bytes) else Path(data).read_bytes()
        if self.data[:4] != b'\xcf\xfa\xed\xfe':
            raise ValueError('Expected a little-endian 64-bit Mach-O slice.')
        self.sections = {}
        self.segments = []
        self.symbols = {}
        self.imports = []
        self.methods = []
        self.starts = []
        self.labels = {}
        ncmds = self.unpack('<I', 16)[0]
        p = 32
        self.cmds = {}
        for _ in range(ncmds):
            cmd, size = self.unpack('<II', p)
            self.cmds[cmd] = p
            if cmd == 0x19:
                seg = self.unpack('<II16sQQQQiiII', p)
                self.segments.append((seg[3], seg[4], seg[5], seg[6], seg[2].rstrip(b'\0').decode()))
                for k in range(seg[9]):
                    s = self.unpack('<16s16sQQ8I', p + 72 + 80*k)
                    name = s[0].rstrip(b'\0').decode()
                    self.sections[(seg[2].rstrip(b'\0').decode(), name)] = (s[2], s[3], s[4])
            p += size
        if 0x80000034 in self.cmds:
            o,n = self.unpack('<II', self.cmds[0x80000034]+8)
            version, starts, imports, symbols, count, fmt, symfmt = self.unpack('<7I', o)
            for i in range(count):
                if fmt in (1,2):
                    w = self.unpack('<I', o+imports+i*(4 if fmt==1 else 8))[0]
                    nameoff = w >> 9
                elif fmt == 3:
                    w = self.unpack('<Q', o+imports+i*16)[0]
                    nameoff = w >> 32
                self.imports.append(self.cstr_file(o+symbols+nameoff))
        if 2 in self.cmds:
            symoff, nsyms, stroff, strsize = self.unpack('<4I', self.cmds[2]+8)
            for i in range(nsyms):
                nstr,typ,sect,desc,value = self.unpack('<IBBHQ',symoff+i*16)
                name = self.cstr_file(stroff+nstr)
                if value:
                    self.symbols[value] = name
                    self.labels[value] = name
        if 0x26 in self.cmds:
            o,n = self.unpack('<II',self.cmds[0x26]+8)
            addr = BASE
            while o < len(self.data):
                v,o = self.uleb(o)
                if not v: break
                addr += v
                self.starts.append(addr)
        a,n,o = self.sections[('__TEXT','__objc_methlist')]
        p = a
        while p < a+n:
            if self.u32(p) == 0:
                p += 4
                continue
            flags,count = self.vunpack('<II',p)
            sz = flags & 0xffff
            if sz not in (12,24) or count>10000:
                raise ValueError((hex(p),hex(flags),count))
            for i in range(count):
                q=p+8+i*sz
                if flags & 0x80000000:
                    nr,tr,ir = self.vunpack('<iii',q)
                    name_addr=q+nr
                    if not flags & 0x40000000:
                        name_addr=self.ptr(name_addr)
                    name=self.cstr(name_addr)
                    types=self.cstr(q+4+tr)
                    imp=q+8+ir
                else:
                    name=self.cstr(self.ptr(q));types=self.cstr(self.ptr(q+8));imp=self.ptr(q+16)
                self.methods.append(dict(name=name,types=types,imp=imp,list=p,entry=q))
                self.labels[imp]=name
            p += 8+count*sz
        self.resolve_class_owners()
        self.dc = None
        if disassembly:
            libname = llvm_library or os.environ.get('LLVM_LIBRARY')
            if not libname:
                for name in ('LLVM', 'LLVM-20', 'LLVM-19', 'LLVM-18', 'LLVM-17'):
                    libname = ctypes.util.find_library(name)
                    if libname: break
            if not libname:
                raise RuntimeError('Set --llvm-library to your libLLVM shared library to disassemble.')
            self.lib = ctypes.CDLL(libname)
            for f in ('LLVMInitializeAArch64TargetInfo','LLVMInitializeAArch64Target','LLVMInitializeAArch64TargetMC','LLVMInitializeAArch64Disassembler'):
                getattr(self.lib,f)()
            self.lib.LLVMCreateDisasm.restype=ctypes.c_void_p
            self.lib.LLVMCreateDisasm.argtypes=[ctypes.c_char_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p]
            self.dc=self.lib.LLVMCreateDisasm(b'aarch64-apple-darwin',None,0,None,None)
            if not self.dc: raise RuntimeError('libLLVM could not create an AArch64 disassembler.')
            self.lib.LLVMDisasmInstruction.restype=ctypes.c_size_t
            self.lib.LLVMDisasmInstruction.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint8),ctypes.c_uint64,ctypes.c_uint64,ctypes.c_char_p,ctypes.c_size_t]
        self.stub_names={}
        self.resolve_stubs()

    def unpack(self,fmt,off): return struct.unpack_from(fmt,self.data,off)
    def off(self,addr):
        for a,n,o,s,name in self.segments:
            if a<=addr<a+s:return o+addr-a
        raise ValueError('unmapped '+hex(addr))
    def vunpack(self,fmt,addr):return self.unpack(fmt,self.off(addr))
    def u32(self,a):return self.vunpack('<I',a)[0]
    def rawptr(self,a):return self.vunpack('<Q',a)[0]
    def ptr(self,a):return self.decode_ptr(self.rawptr(a))
    def decode_ptr(self,w):
        if w == 0:return 0
        if w>>62 & 1:
            idx=w&0xffff
            return self.imports[idx] if idx<len(self.imports) else f'import#{idx}'
        v=(BASE+(w&0xffffffff)) if w>>63 else (w&((1<<43)-1))
        if 0<v<len(self.data):v+=BASE
        return v
    def cstr_file(self,o):return self.data[o:self.data.index(0,o)].decode('utf-8','replace')
    def cstr(self,a):return self.cstr_file(self.off(a)) if a else ''
    def uleb(self,o):
        n=0;s=0
        while True:
            b=self.data[o];o+=1;n|=(b&127)<<s
            if b<128:return n,o
            s+=7
    def resolve_class_owners(self):
        owners={}
        a,n,o=self.sections[('__DATA_CONST','__objc_classlist')]
        for q in range(a,a+n,8):
            cls=self.ptr(q)
            if not isinstance(cls,int):continue
            for meta in (False,True):
                c=self.ptr(cls) if meta else cls
                if not isinstance(c,int):continue
                ro=self.ptr(c+32)&~7
                name=self.cstr(self.ptr(ro+24))
                ml=self.ptr(ro+32)
                if ml:owners[ml]=('+' if meta else '-')+'['+name+' '
        a,n,o=self.sections[('__DATA_CONST','__objc_catlist')]
        for q in range(a,a+n,8):
            cat=self.ptr(q)
            name=self.cstr(self.ptr(cat))
            cls=self.ptr(cat+8)
            if isinstance(cls,str):cls=cls.replace('_OBJC_CLASS_$_','')
            else:cls=self.cstr(self.ptr((self.ptr(cls+32)&~7)+24))
            for offs,kind in ((16,'-'),(24,'+')):
                ml=self.ptr(cat+offs)
                if ml:owners[ml]=f'{kind}[{cls}({name}) '
        for m in self.methods:
            m['owner']=owners.get(m['list'],'?[')
            m['label']=m['owner']+m['name']+']'
            self.labels[m['imp']]=m['label']
    def dis_one(self,a):
        if not self.dc: raise RuntimeError('Disassembly was not enabled.')
        b=(ctypes.c_uint8*4).from_buffer_copy(self.data[self.off(a):self.off(a)+4])
        out=ctypes.create_string_buffer(512)
        n=self.lib.LLVMDisasmInstruction(self.dc,b,4,a,out,512)
        return out.value.decode().strip() if n else '.word '+hex(self.u32(a))
    def resolve_stubs(self):
        for key in (('__TEXT','__auth_stubs'),('__TEXT','__objc_stubs')):
            a,n,o=self.sections[key]
            width=16 if key[1]=='__auth_stubs' else 32
            for q in range(a,a+n,width):
                pages={};name=None
                for p in range(q,q+width,4):
                    w=self.u32(p)
                    if w&0x9f000000==0x90000000:
                        imm=((w>>29)&3)|(((w>>5)&0x7ffff)<<2)
                        if imm&(1<<20):imm-=1<<21
                        pages[w&31]=(p&~0xfff)+(imm<<12)
                    elif w&0xffc00000==0x91000000 and ((w>>5)&31) in pages:
                        pages[w&31]=pages[(w>>5)&31]+((w>>10)&0xfff)
                    elif w&0xffc00000==0xf9400000 and ((w>>5)&31) in pages:
                        addr=pages[(w>>5)&31]+(((w>>10)&0xfff)<<3)
                        try:
                            x=self.ptr(addr)
                            name=x if isinstance(x,str) else self.cstr(x)
                        except (ValueError,IndexError,struct.error):pass
                        break
                if name:self.stub_names[q]=name
    def describe(self,a):
        if isinstance(a,str):return a
        if a in self.stub_names:return self.stub_names[a]
        if a in self.labels:return self.labels[a]
        for (seg,name),(start,size,o) in self.sections.items():
            if start<=a<start+size:
                if name in ('__cstring','__objc_methname','__objc_classname','__objc_methtype'):
                    return repr(self.cstr(a))
                if name in ('__objc_selrefs','__objc_classrefs','__got','__auth_got','__objc_superrefs'):
                    p=self.ptr(a)
                    return self.describe(p) if isinstance(p,str) or (isinstance(p,int) and BASE<=p<BASE+len(self.data)) else hex(p)
                if name=='__cfstring':
                    try:return 'CFString '+repr(self.cstr(self.ptr(a+16)))
                    except Exception:pass
                if seg=='__DATA' and name=='__data' and a%8==0:
                    try:
                        v=self.ptr(a)
                        ca,cn,co=self.sections[('__DATA_CONST','__cfstring')]
                        if isinstance(v,int) and ca<=v<ca+cn:return 'pointer -> '+self.describe(v)
                    except Exception:pass
                if seg=='__TEXT' and name=='__const':
                    return 'double='+str(self.vunpack('<d',a)[0])
                return seg+','+name+'+'+hex(a-start)
        return ''
    def dis(self,start,end=None):
        if end is None:
            i=bisect.bisect_right(self.starts,start)
            end=self.starts[i] if i<len(self.starts) else start+1024
        pages={}
        lines=[]
        for p in range(start,end,4):
            s=self.dis_one(p);w=self.u32(p);comment=''
            m=re.search(r'^b(?:l|\.[a-z]+)?\s+#?(-?(?:0x[0-9a-f]+|\d+))$',s)
            if m:
                target=p+int(m[1],0);comment=f'{target:#x} '+self.describe(target)
            if w&0x9f000000==0x90000000:
                imm=((w>>29)&3)|(((w>>5)&0x7ffff)<<2)
                if imm&(1<<20):imm-=1<<21
                pages[w&31]=(p&~0xfff)+(imm<<12)
                comment=f'page {pages[w&31]:#x}'
            elif w&0xffc00000==0x91000000:
                rn=(w>>5)&31;rd=w&31;imm=(w>>10)&0xfff
                if rn in pages:
                    v=pages[rn]+imm;comment=f'{v:#x} '+self.describe(v);pages[rd]=v
            elif w&0xffc00000 in (0xf9400000,0xfd400000):
                rn=(w>>5)&31;imm=((w>>10)&0xfff)*8
                if rn in pages:
                    v=pages[rn]+imm;comment=f'{v:#x} '+self.describe(v)
                if w&0xffc00000==0xf9400000:pages.pop(w&31,None)
            else:
                op=s.split()[0]
                dest=re.match(r'^\S+\s+[xw](\d+)',s)
                if dest and not op.startswith(('st','b','cb','tb')) and op not in ('cmp','cmn','tst'):
                    pages.pop(int(dest[1]),None)
                if op=='bl':
                    for reg in range(19):pages.pop(reg,None)
            lines.append(f'{p:016x}  {s:48}'+(' ; '+comment if comment else ''))
        return '\n'.join(lines)

def split_slices(data):
    if data[:4] == b'\xca\xfe\xba\xbe':
        count = struct.unpack_from('>I', data, 4)[0]
        result = []
        for i in range(count):
            cpu, subtype, offset, size, alignment = struct.unpack_from('>5I', data, 8+20*i)
            if offset+size > len(data): raise ValueError('Slice exceeds file bounds.')
            result.append(data[offset:offset+size])
        return result
    if data[:4] == b'\xcf\xfa\xed\xfe': return [data]
    raise ValueError('Unsupported file format: expected this build\'s universal or thin Mach-O.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--slice', type=int, default=0)
    parser.add_argument('--match', default=r'adjustedColor|colorForANSIColor|reportColor:')
    parser.add_argument('--disassemble', action='store_true')
    parser.add_argument('--llvm-library')
    args = parser.parse_args()
    data = args.binary.read_bytes()
    slices = split_slices(data)
    if not 0 <= args.slice < len(slices): parser.error('Slice index is out of range.')
    print('Executable SHA-256:', hashlib.sha256(data).hexdigest())
    print('Selected slice:', args.slice)
    m = MachO(slices[args.slice], llvm_library=args.llvm_library, disassembly=args.disassemble)
    pattern = re.compile(args.match)
    for method in m.methods:
        if pattern.search(method['name']):
            print(f"{method['imp']:#x} {method['label']} {method['types']}")
            if args.disassemble: print(m.dis(method['imp']), '\n')


if __name__ == '__main__':
    main()
