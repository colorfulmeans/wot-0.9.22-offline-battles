#!/bin/sh
# The exported i386 interpreter initially used GCC's default x87 arithmetic.
# Build the independent test host with the same double-precision SSE2 policy
# as the reviewed native extension. Do not weaken any comparison tolerance.
# A fresh official CPython source archive is supplied by the workflow; this
# script and the subsequent native validation run have networking disabled.
set -eu
mkdir -p /work/out
{
    /opt/python27/bin/python2.7 -B -c 'import sys,sysconfig; print(sys.version); print(sysconfig.get_config_var("CC")); print(sysconfig.get_config_var("CFLAGS"))'
    tar -xf /work/Python-2.7.18.tar.xz -C /work
    cd /work/Python-2.7.18
    CC='gcc -m32 -msse2 -mfpmath=sse' CXX='g++ -m32 -msse2 -mfpmath=sse' \
    CFLAGS='-O2 -msse2 -mfpmath=sse -fno-fast-math -ffp-contract=off -fwrapv -fno-strict-aliasing -Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types' \
    LDFLAGS='-m32' ./configure --prefix=/opt/python27 --disable-shared --with-ensurepip=no
    make -j2
    make install
    /opt/python27/bin/python2.7 -B -c 'import sys,struct,sysconfig,math,zlib,bz2,ctypes; assert sys.version_info[:3]==(2,7,18); assert struct.calcsize("P")==4; flags=sysconfig.get_config_var("CFLAGS"); assert "-mfpmath=sse" in flags; print(sys.version); print(flags)'
} > /work/out/prepare-cpython27-sse2.log 2>&1 || {
    tail -100 /work/out/prepare-cpython27-sse2.log
    exit 1
}
cd /work/repo
exec /usr/bin/python3 tools/build_verify_native_migration.py
