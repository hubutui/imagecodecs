# test_imagecodecs.py

# Copyright (c) 2018-2020, Christoph Gohlke
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
# * Neither the name of the copyright holders nor the names of any
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Unittests for the imagecodecs package.

:Author:
  `Christoph Gohlke <https://www.lfd.uci.edu/~gohlke/>`_

:Organization:
  Laboratory for Fluorescence Dynamics. University of California, Irvine

:License: BSD 3-Clause

:Version: 2020.5.30

"""

import sys
import os
import io
import re
import glob
import mmap
import pathlib
import tempfile
import importlib
import os.path as osp

import pytest

import numpy
from numpy.testing import assert_array_equal, assert_allclose

try:
    import imagecodecs
    from imagecodecs import _imagecodecs
    from imagecodecs.imagecodecs import _add_codec, _extensions
    from imagecodecs._imagecodecs import (
        zlib, lzma, bz2, zstd, lz4, lzf, blosc, brotli, snappy, zopfli,
        bitshuffle, tifffile, czifile
    )
except ImportError as exc:
    pytest.exit(str(exc))


TEST_DIR = osp.dirname(__file__)
IS_32BIT = sys.maxsize < 2**32
IS_WIN = sys.platform == 'win32'
# running on Windows development computer?
IS_CG = os.environ.get('COMPUTERNAME', '').startswith('CG-')
# running in cibuildwheel environment?
IS_CI = os.environ.get('CIBUILDWHEEL', False)

numpy.set_printoptions(suppress=True, precision=5)


###############################################################################

def test_version():
    """Assert imagecodecs versions match docstrings."""
    ver = ':Version: ' + imagecodecs.__version__
    assert ver in __doc__
    assert ver in imagecodecs.__doc__


@pytest.mark.parametrize('name', _extensions())
def test_module_exist(name):
    """Assert extension modules are present."""
    try:
        exists = bool(importlib.import_module('._' + name, 'imagecodecs'))
    except ImportError:
        exists = False
    if exists:
        return
    if not IS_CG and not IS_CI:
        pytest.xfail(f'imagecodecs._{name} may be missing')
    elif name in ('jpeg12', 'lerc') and IS_CI:
        pytest.xfail(f'imagecodecs._{name} may be missing')
    assert exists, f'no module named imagecodecs._{name}'


@pytest.mark.parametrize('name', [
    'bitshuffle', 'blosc', 'brotli', 'lz4', 'lzf', 'lzma', 'zopfli', 'zstd',
    'tifffile', 'czifile'])
def test_dependency_exist(name):
    """Assert third-party Python packages are present."""
    mayfail = not IS_CG and not IS_CI
    try:
        importlib.import_module(name)
    except ImportError:
        if mayfail:
            pytest.skip(f'{name} may be missing')
        raise


def test_version_functions():
    """Test imagecodecs version functions."""
    assert imagecodecs.version().startswith('imagecodecs')
    assert 'imagecodecs' in imagecodecs.version(dict)
    assert imagecodecs.version(tuple)[1].startswith('cython')
    assert _imagecodecs.version().startswith('imagecodecs.py')
    assert 'imagecodecs.py' in _imagecodecs.version(dict)


@pytest.mark.skipif(sys.version_info < (3, 7), reason='no __getattr__')
def test_stubs():
    """Test stub attributes for non-existing extension."""
    with pytest.raises(AttributeError):
        imagecodecs._STUB
    _add_codec('_stub')
    assert not imagecodecs._STUB
    assert not imagecodecs._stub_check(b'')
    assert imagecodecs._stub_version() == '_stub n/a'
    with pytest.raises(imagecodecs.DelayedImportError):
        imagecodecs._STUB.attr
    with pytest.raises(imagecodecs.DelayedImportError):
        imagecodecs._stub_encode(b'')
    with pytest.raises(imagecodecs.DelayedImportError):
        imagecodecs._stub_decode(b'')
    with pytest.raises(imagecodecs.DelayedImportError):
        raise imagecodecs._stubError()


def test_dir():
    """Assert __dir__ contains delay-loaded attributes."""
    d = dir(imagecodecs)
    assert 'NONE' in d
    assert 'LZW' in d
    assert 'jxr_decode' in d


@pytest.mark.skipif(not imagecodecs.NUMPY, reason='Numpy codec missing')
@pytest.mark.parametrize('codec', ['none', 'str', 'ext', 'codec', 'list',
                                   'fail'])
@pytest.mark.parametrize('filearg', ['str', 'pathlib', 'bytesio', 'bytes'])
def test_imread_imwrite(filearg, codec):
    """Test imread and imwrite functions."""
    imread = imagecodecs.imread
    imwrite = imagecodecs.imwrite
    data = image_data('rgba', 'uint8')

    if codec == 'ext':
        # auto detect codec from file extension or trial&error
        with TempFileName(suffix='.npy') as fileobj:
            if filearg == 'pathlib':
                fileobj = pathlib.Path(fileobj)
            if filearg == 'bytes':
                fileobj = imagecodecs.numpy_encode(data)
            elif filearg == 'bytesio':
                # must specify codec
                fileobj = io.BytesIO()
                imwrite(fileobj, data, codec=imagecodecs.numpy_encode)
            else:
                imwrite(fileobj, data, level=99)
            if filearg == 'bytesio':
                fileobj.seek(0)
            im, codec = imread(fileobj, return_codec=True)
            assert codec == imagecodecs.numpy_decode
            assert_array_equal(data, im)
        return

    if codec == 'none':
        encode = None
        decode = None
    elif codec == 'str':
        encode = 'numpy'
        decode = 'numpy'
    elif codec == 'list':
        encode = 'npz'
        decode = ['npz']
    elif codec == 'fail':
        encode = 'fail'
        decode = 'fail'
    elif codec == 'codec':
        encode = imagecodecs.numpy_encode
        decode = imagecodecs.numpy_decode

    with TempFileName() as fileobj:
        if filearg == 'pathlib':
            fileobj = pathlib.Path(fileobj)
        elif filearg == 'bytesio':
            fileobj = io.BytesIO()

        if filearg == 'bytes':
            fileobj = imagecodecs.numpy_encode(data)
        elif encode in (None, 'fail'):
            with pytest.raises(ValueError):
                imwrite(fileobj, data, codec=encode)
            imwrite(fileobj, data, codec=imagecodecs.numpy_encode)
        else:
            imwrite(fileobj, data, codec=encode)

        if filearg == 'bytesio':
            fileobj.seek(0)

        if codec == 'fail':
            with pytest.raises(ValueError):
                im = imread(fileobj, codec=decode)
            return

        im, ret = imread(fileobj, codec=decode, return_codec=True)
        assert ret == imagecodecs.numpy_decode
        assert_array_equal(data, im)


def test_none():
    """Test NOP codec."""
    data = b'None'
    assert imagecodecs.none_encode(data) is data
    assert imagecodecs.none_decode(data) is data


@pytest.mark.skipif(not imagecodecs.BITORDER, reason='Bitorder missing')
def test_bitorder():
    """Test BitOrder codec with bytes."""
    decode = imagecodecs.bitorder_decode
    data = b'\x01\x00\x9a\x02'
    reverse = b'\x80\x00Y@'
    # return new string
    assert decode(data) == reverse
    assert data == b'\x01\x00\x9a\x02'
    # provide output
    out = bytearray(len(data))
    decode(data, out=out)
    assert out == reverse
    assert data == b'\x01\x00\x9a\x02'
    # inplace
    decode(data, out=data)
    assert data == reverse
    # bytes range
    assert BYTES == decode(readfile('bytes.bitorder.bin'))


@pytest.mark.skipif(not imagecodecs.BITORDER, reason='Bitorder missing')
def test_bitorder_ndarray():
    """Test BitOrder codec with ndarray."""
    decode = imagecodecs.bitorder_decode
    data = numpy.array([1, 666], dtype='uint16')
    reverse = numpy.array([128, 16473], dtype='uint16')
    # return new array
    assert_array_equal(decode(data), reverse)
    # inplace
    decode(data, out=data)
    assert_array_equal(data, numpy.array([128, 16473], dtype='uint16'))
    # array view
    data = numpy.array([[1, 666, 1431655765, 62],
                        [2, 667, 2863311530, 32],
                        [3, 668, 1431655765, 30]], dtype='uint32')
    reverse = numpy.array([[1, 666, 1431655765, 62],
                           [2, 16601, 1431655765, 32],
                           [3, 16441, 2863311530, 30]], dtype='uint32')
    assert_array_equal(decode(data[1:, 1:3]), reverse[1:, 1:3])
    # array view inplace
    decode(data[1:, 1:3], out=data[1:, 1:3])
    assert_array_equal(data, reverse)


@pytest.mark.skipif(not imagecodecs.PACKINTS, reason='Packints missing')
def test_packints_decode():
    """Test PackInts decoder."""
    decode = imagecodecs.packints_decode

    decoded = decode(b'', 'B', 1)
    assert len(decoded) == 0

    decoded = decode(b'a', 'B', 1)
    assert tuple(decoded) == (0, 1, 1, 0, 0, 0, 0, 1)

    decoded = decode(b'ab', 'B', 2)
    assert tuple(decoded) == (1, 2, 0, 1, 1, 2, 0, 2)

    decoded = decode(b'abcd', 'B', 3)
    assert tuple(decoded) == (3, 0, 2, 6, 1, 1, 4, 3, 3, 1)

    decoded = decode(numpy.frombuffer(b'abcd', dtype='uint8'), 'B', 3)
    assert tuple(decoded) == (3, 0, 2, 6, 1, 1, 4, 3, 3, 1)


PACKBITS_DATA = [
    (b'', b''),
    (b'X', b'\x00X'),
    (b'123', b'\x02123'),
    (b'112112', b'\xff1\x002\xff1\x002'),
    (b'1122', b'\xff1\xff2'),
    (b'1' * 126, b'\x831'),
    (b'1' * 127, b'\x821'),
    (b'1' * 128, b'\x811'),
    (b'1' * 127 + b'foo', b'\x821\x00f\xffo'),
    (b'12345678' * 16,  # literal 128
     b'\x7f1234567812345678123456781234567812345678123456781234567812345678'
     b'1234567812345678123456781234567812345678123456781234567812345678'),
    (b'12345678' * 17,
     b'~1234567812345678123456781234567812345678123456781234567812345678'
     b'123456781234567812345678123456781234567812345678123456781234567\x08'
     b'812345678'),
    (b'1' * 128 + b'12345678' * 17,
     b'\x821\xff1~2345678123456781234567812345678123456781234567812345678'
     b'1234567812345678123456781234567812345678123456781234567812345678'
     b'12345678\x0712345678'),
    (b'\xaa\xaa\xaa\x80\x00\x2a\xaa\xaa\xaa\xaa\x80\x00'
     b'\x2a\x22\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa',
     b'\xfe\xaa\x02\x80\x00\x2a\xfd\xaa\x03\x80\x00\x2a\x22\xf7\xaa')
]


@pytest.mark.skipif(not imagecodecs.PACKBITS, reason='Packbits missing')
@pytest.mark.parametrize('data', range(len(PACKBITS_DATA)))
@pytest.mark.parametrize('codec', ['encode', 'decode'])
def test_packbits(codec, data):
    """Test PackBits codec."""
    encode = imagecodecs.packbits_encode
    decode = imagecodecs.packbits_decode
    uncompressed, compressed = PACKBITS_DATA[data]
    if codec == 'decode':
        assert decode(compressed) == uncompressed
    elif codec == 'encode':
        try:
            assert encode(uncompressed) == compressed
        except AssertionError:
            # roundtrip
            assert decode(encode(uncompressed)) == uncompressed


@pytest.mark.parametrize('data', range(len(PACKBITS_DATA)))
def test_packbits_py(data):
    """Test pure Python PackBits decoder."""
    uncompressed, compressed = PACKBITS_DATA[data]
    assert _imagecodecs.packbits_decode(compressed) == uncompressed


@pytest.mark.skipif(not imagecodecs.PACKBITS, reason='Packbits missing')
def test_packbits_nop():
    """Test PackBits decoding empty data."""
    decode = imagecodecs.packbits_decode
    assert decode(b'\x80') == b''
    assert decode(b'\x80\x80') == b''


@pytest.mark.skipif(not imagecodecs.PACKBITS, reason='Packbits missing')
@pytest.mark.parametrize('output', [None, 'array'])
@pytest.mark.parametrize('codec', ['encode', 'decode'])
def test_packbits_array(codec, output):
    """Test PackBits codec with arrays."""
    encode = imagecodecs.packbits_encode
    decode = imagecodecs.packbits_decode
    uncompressed, compressed = PACKBITS_DATA[-1]
    shape = (2, 7, len(uncompressed))
    data = numpy.empty(shape, dtype='uint8')
    data[..., :] = numpy.frombuffer(uncompressed, dtype='uint8')
    compressed = compressed * (shape[0] * shape[1])
    if codec == 'encode':
        if output == 'array':
            out = numpy.empty(data.size, data.dtype)
            assert_array_equal(encode(data, out=out),
                               numpy.frombuffer(compressed, dtype='uint8'))
        else:
            assert encode(data) == compressed
    else:
        if output == 'array':
            out = numpy.empty(data.size, data.dtype)
            assert_array_equal(decode(compressed, out=out), data.flat)
        else:
            assert decode(compressed) == data.tobytes()


@pytest.mark.filterwarnings('ignore:invalid value encountered')
@pytest.mark.parametrize('output', ['new', 'out', 'inplace'])
@pytest.mark.parametrize('codec', ['encode', 'decode'])
@pytest.mark.parametrize('kind', [
    'u1', 'u2', 'u4', 'u8', 'i1', 'i2', 'i4', 'i8', 'f4', 'f8', 'B', 'b'])
@pytest.mark.parametrize('func', ['delta', 'xor'])
def test_delta(output, kind, codec, func):
    """Test Delta codec."""
    if func == 'delta':
        if not imagecodecs.DELTA:
            pytest.skip('Delta missing')
        encode = imagecodecs.delta_encode
        decode = imagecodecs.delta_decode
        encode_py = _imagecodecs.delta_encode
        # decode_py = _imagecodecs.delta_decode
    elif func == 'xor':
        if not imagecodecs.XOR:
            pytest.skip('Xor missing')
        encode = imagecodecs.xor_encode
        decode = imagecodecs.xor_decode
        encode_py = _imagecodecs.xor_encode
        # decode_py = _imagecodecs.xor_decode

    bytetype = bytearray
    if kind == 'b':
        bytetype = bytes
        kind = 'B'

    axis = -2  # do not change
    dtype = numpy.dtype(kind)
    if kind[0] in 'iuB':
        low = numpy.iinfo(dtype).min
        high = numpy.iinfo(dtype).max
        data = numpy.random.randint(low, high, size=33 * 31 * 3,
                                    dtype=dtype).reshape(33, 31, 3)
    else:
        low, high = -1e5, 1e5
        data = numpy.random.randint(low, high, size=33 * 31 * 3,
                                    dtype='i4').reshape(33, 31, 3)
        data = data.astype(dtype)

    data[16, 14] = [0, 0, 0]
    data[16, 15] = [low, high, low]
    data[16, 16] = [high, low, high]
    data[16, 17] = [low, high, low]
    data[16, 18] = [high, low, high]
    data[16, 19] = [0, 0, 0]

    if kind == 'B':
        # data = data.reshape(-1)
        data = data.tobytes()
        diff = encode_py(data, axis=0)
        if output == 'new':
            if codec == 'encode':
                encoded = encode(data, out=bytetype)
                assert encoded == diff
            elif codec == 'decode':
                decoded = decode(diff, out=bytetype)
                assert decoded == data
        elif output == 'out':
            if codec == 'encode':
                encoded = bytetype(len(data))
                encode(data, out=encoded)
                assert encoded == diff
            elif codec == 'decode':
                decoded = bytetype(len(data))
                decode(diff, out=decoded)
                assert decoded == data
        elif output == 'inplace':
            if codec == 'encode':
                encoded = bytetype(data)
                encode(encoded, out=encoded)
                assert encoded == diff
            elif codec == 'decode':
                decoded = bytetype(diff)
                decode(decoded, out=decoded)
                assert decoded == data
    else:
        # if func == 'xor' and kind in ('f4', 'f8'):
        #      with pytest.raises(ValueError):
        #          encode(data, axis=axis)
        #      pytest.xfail("XOR codec not implemented for float data")
        diff = encode_py(data, axis=-2)

        if output == 'new':
            if codec == 'encode':
                encoded = encode(data, axis=axis)
                assert_array_equal(encoded, diff)
            elif codec == 'decode':
                decoded = decode(diff, axis=axis)
                assert_array_equal(decoded, data)
        elif output == 'out':
            if codec == 'encode':
                encoded = numpy.zeros_like(data)
                encode(data, axis=axis, out=encoded)
                assert_array_equal(encoded, diff)
            elif codec == 'decode':
                decoded = numpy.zeros_like(data)
                decode(diff, axis=axis, out=decoded)
                assert_array_equal(decoded, data)
        elif output == 'inplace':
            if codec == 'encode':
                encoded = data.copy()
                encode(encoded, axis=axis, out=encoded)
                assert_array_equal(encoded, diff)
            elif codec == 'decode':
                decoded = diff.copy()
                decode(decoded, axis=axis, out=decoded)
                assert_array_equal(decoded, data)


@pytest.mark.skipif(not imagecodecs.FLOATPRED, reason='FloatPred missing')
@pytest.mark.parametrize('output', ['new', 'out'])
@pytest.mark.parametrize('codec', ['encode', 'decode'])
@pytest.mark.parametrize('endian', ['le', 'be'])
@pytest.mark.parametrize('planar', ['rgb', 'rrggbb'])
def test_floatpred(planar, endian, output, codec):
    """Test FloatPred codec."""
    encode = imagecodecs.floatpred_encode
    decode = imagecodecs.floatpred_decode
    data = numpy.fromfile(
        datafiles('rgb.bin'), dtype='<f4').reshape(33, 31, 3)

    if planar == 'rgb':
        axis = -2
        if endian == 'le':
            encoded = numpy.fromfile(
                datafiles('rgb.floatpred_le.bin'), dtype='<f4')
            encoded = encoded.reshape(33, 31, 3)
            if output == 'new':
                if codec == 'decode':
                    assert_array_equal(decode(encoded, axis=axis), data)
                elif codec == 'encode':
                    assert_array_equal(encode(data, axis=axis), encoded)
            elif output == 'out':
                out = numpy.empty_like(data)
                if codec == 'decode':
                    decode(encoded, axis=axis, out=out)
                    assert_array_equal(out, data)
                elif codec == 'encode':
                    out = numpy.empty_like(data)
                    encode(data, axis=axis, out=out)
                    assert_array_equal(out, encoded)
        elif endian == 'be':
            data = data.astype('>f4')
            encoded = numpy.fromfile(
                datafiles('rgb.floatpred_be.bin'), dtype='>f4')
            encoded = encoded.reshape(33, 31, 3)
            if output == 'new':
                if codec == 'decode':
                    assert_array_equal(decode(encoded, axis=axis), data)
                elif codec == 'encode':
                    assert_array_equal(encode(data, axis=axis), encoded)
            elif output == 'out':
                out = numpy.empty_like(data)
                if codec == 'decode':
                    decode(encoded, axis=axis, out=out)
                    assert_array_equal(out, data)
                elif codec == 'encode':
                    out = numpy.empty_like(data)
                    encode(data, axis=axis, out=out)
                    assert_array_equal(out, encoded)
    elif planar == 'rrggbb':
        axis = -1
        data = numpy.ascontiguousarray(numpy.moveaxis(data, 2, 0))
        if endian == 'le':
            encoded = numpy.fromfile(
                datafiles('rrggbb.floatpred_le.bin'), dtype='<f4')
            encoded = encoded.reshape(3, 33, 31)
            if output == 'new':
                if codec == 'decode':
                    assert_array_equal(decode(encoded, axis=axis), data)
                elif codec == 'encode':
                    assert_array_equal(encode(data, axis=axis), encoded)
            elif output == 'out':
                out = numpy.empty_like(data)
                if codec == 'decode':
                    decode(encoded, axis=axis, out=out)
                    assert_array_equal(out, data)
                elif codec == 'encode':
                    out = numpy.empty_like(data)
                    encode(data, axis=axis, out=out)
                    assert_array_equal(out, encoded)
        elif endian == 'be':
            data = data.astype('>f4')
            encoded = numpy.fromfile(
                datafiles('rrggbb.floatpred_be.bin'), dtype='>f4')
            encoded = encoded.reshape(3, 33, 31)
            if output == 'new':
                if codec == 'decode':
                    assert_array_equal(decode(encoded, axis=axis), data)
                elif codec == 'encode':
                    assert_array_equal(encode(data, axis=axis), encoded)
            elif output == 'out':
                out = numpy.empty_like(data)
                if codec == 'decode':
                    decode(encoded, axis=axis, out=out)
                    assert_array_equal(out, data)
                elif codec == 'encode':
                    out = numpy.empty_like(data)
                    encode(data, axis=axis, out=out)
                    assert_array_equal(out, encoded)


@pytest.mark.skipif(not imagecodecs.LZW, reason='LZW missing')
def test_lzw_corrupt():
    """Test LZW decoder with corrupt stream."""
    # reported by S Richter on 2020.2.17
    fname = datafiles('corrupt.lzw.bin')
    with open(fname, 'rb') as fh:
        encoded = fh.read()
    assert imagecodecs.lzw_check(encoded)
    with pytest.raises(RuntimeError):
        imagecodecs.lzw_decode(encoded, out=655360)


@pytest.mark.skipif(not imagecodecs.LZW, reason='LZW missing')
def test_lzw_msb():
    """Test LZW decoder with MSB."""
    # TODO: add test_lzw_lsb
    decode = imagecodecs.lzw_decode
    for encoded, decoded in [
            (b'\x80\x1c\xcc\'\x91\x01\xa0\xc2m6\x99NB\x03\xc9\xbe\x0b'
             b'\x07\x84\xc2\xcd\xa68|"\x14 3\xc3\xa0\xd1c\x94\x02\x02\x80',
             b'say hammer yo hammer mc hammer go hammer'),
            (b'\x80\x18M\xc6A\x01\xd0\xd0e\x10\x1c\x8c\xa73\xa0\x80\xc7\x02'
             b'\x10\x19\xcd\xe2\x08\x14\x10\xe0l0\x9e`\x10\x10\x80',
             b'and the rest can go and play'),
            (b'\x80\x18\xcc&\xe19\xd0@t7\x9dLf\x889\xa0\xd2s',
             b"can't touch this"),
            (b'\x80@@', b'')]:
        assert imagecodecs.lzw_check(encoded)
        assert decode(encoded) == decoded


@pytest.mark.skipif(not (imagecodecs.LZW and imagecodecs.DELTA), reason='skip')
@pytest.mark.parametrize('output', ['new', 'size', 'ndarray', 'bytearray'])
def test_lzw_decode(output):
    """Test LZW decoder of input with horizontal differencing."""
    decode = imagecodecs.lzw_decode
    delta_decode = imagecodecs.delta_decode
    encoded = readfile('bytes.lzw_horizontal.bin')
    assert imagecodecs.lzw_check(encoded)
    decoded_size = len(BYTES)

    if output == 'new':
        decoded = decode(encoded)
        decoded = numpy.frombuffer(decoded, 'uint8').reshape(16, 16)
        delta_decode(decoded, out=decoded, axis=-1)
        assert_array_equal(BYTESIMG, decoded)
    elif output == 'size':
        decoded = decode(encoded, out=decoded_size)
        decoded = numpy.frombuffer(decoded, 'uint8').reshape(16, 16)
        delta_decode(decoded, out=decoded, axis=-1)
        assert_array_equal(BYTESIMG, decoded)
        # with pytest.raises(RuntimeError):
        decode(encoded, buffersize=32, out=decoded_size)
    elif output == 'ndarray':
        decoded = numpy.empty_like(BYTESIMG)
        decode(encoded, out=decoded.reshape(-1))
        delta_decode(decoded, out=decoded, axis=-1)
        assert_array_equal(BYTESIMG, decoded)
    elif output == 'bytearray':
        decoded = bytearray(decoded_size)
        decode(encoded, out=decoded)
        decoded = numpy.frombuffer(decoded, 'uint8').reshape(16, 16)
        delta_decode(decoded, out=decoded, axis=-1)
        assert_array_equal(BYTESIMG, decoded)


@pytest.mark.skipif(not imagecodecs.LZW, reason='LZW missing')
def test_lzw_decode_image_noeoi():
    """Test LZW decoder of input without EOI 512x512u2."""
    decode = imagecodecs.lzw_decode
    fname = datafiles('image_noeoi.lzw.bin')
    with open(fname, 'rb') as fh:
        encoded = fh.read()
    fname = datafiles('image_noeoi.bin')
    with open(fname, 'rb') as fh:
        decoded_known = fh.read()
    assert imagecodecs.lzw_check(encoded)
    # new output
    decoded = decode(encoded)
    assert decoded == decoded_known
    # provide output
    decoded = bytearray(len(decoded))
    decode(encoded, out=decoded)
    assert decoded == decoded_known
    # truncated output
    decoded = bytearray(100)
    decode(encoded, out=decoded)
    assert len(decoded) == 100


@pytest.mark.filterwarnings('ignore: PY_SSIZE_T_CLEAN')
@pytest.mark.parametrize('output', [
    'new', 'bytearray', 'out', 'size', 'excess', 'trunc'])
@pytest.mark.parametrize('length', [0, 2, 31 * 33 * 3])
@pytest.mark.parametrize('func', ['encode', 'decode'])
@pytest.mark.parametrize('codec', [
    'zlib', 'bz2', 'blosc', 'lzma', 'zstd', 'lzf', 'lz4', 'lz4h',
    'bitshuffle', 'brotli', 'zopfli', 'snappy'])
def test_compressors(codec, func, output, length):
    """Test various non-image codecs."""
    if length:
        data = numpy.random.randint(255, size=length, dtype='uint8').tobytes()
    else:
        data = b''

    if codec == 'blosc':
        if not imagecodecs.BLOSC or blosc is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.blosc_encode
        decode = imagecodecs.blosc_decode
        check = imagecodecs.blosc_check
        level = 9
        encoded = blosc.compress(data, clevel=level)
    elif codec == 'zlib':
        if not imagecodecs.ZLIB or zlib is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.zlib_encode
        decode = imagecodecs.zlib_decode
        check = imagecodecs.zlib_check
        level = 5
        encoded = zlib.compress(data, level)
    elif codec == 'lzma':
        if not imagecodecs.LZMA or lzma is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.lzma_encode
        decode = imagecodecs.lzma_decode
        check = imagecodecs.lzma_check
        level = 6
        encoded = lzma.compress(data)
    elif codec == 'zstd':
        if not imagecodecs.ZSTD or zstd is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.zstd_encode
        decode = imagecodecs.zstd_decode
        check = imagecodecs.zstd_check
        level = 5
        if length == 0:
            # bug in zstd.compress?
            encoded = encode(data, level)
        else:
            encoded = zstd.compress(data, level)
    elif codec == 'lzf':
        if not imagecodecs.LZF or lzf is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.lzf_encode
        decode = imagecodecs.lzf_decode
        check = imagecodecs.lzf_check
        level = 1
        encoded = lzf.compress(data, ((len(data) * 33) >> 5) + 1)
        if encoded is None:
            pytest.xfail("lzf can't compress empty input")
    elif codec == 'lz4':
        if not imagecodecs.LZ4 or lz4 is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.lz4_encode
        decode = imagecodecs.lz4_decode
        check = imagecodecs.lz4_check
        level = 1
        encoded = lz4.block.compress(data, store_size=False)
    elif codec == 'lz4h':
        if not imagecodecs.LZ4 or lz4 is None:
            pytest.skip(f'{codec} missing')

        def encode(*args, **kwargs):
            return imagecodecs.lz4_encode(*args, header=True, **kwargs)

        def decode(*args, **kwargs):
            return imagecodecs.lz4_decode(*args, header=True, **kwargs)

        check = imagecodecs.lz4_check
        level = 1
        encoded = lz4.block.compress(data, store_size=True)
    elif codec == 'bz2':
        if not imagecodecs.BZ2 or bz2 is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.bz2_encode
        decode = imagecodecs.bz2_decode
        check = imagecodecs.bz2_check
        level = 9
        encoded = bz2.compress(data, compresslevel=level)
    elif codec == 'bitshuffle':
        if not imagecodecs.BITSHUFFLE or bitshuffle is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.bitshuffle_encode
        decode = imagecodecs.bitshuffle_decode
        check = imagecodecs.bitshuffle_check
        level = 0
        encoded = bitshuffle.bitshuffle(
            numpy.frombuffer(data, 'uint8')).tobytes()
    elif codec == 'brotli':
        if not imagecodecs.BROTLI or brotli is None:
            pytest.skip(f'{codec} missing')
        if func == 'encode' and length == 0:
            # TODO: why?
            pytest.xfail('python-brotli returns different valid results')
        encode = imagecodecs.brotli_encode
        decode = imagecodecs.brotli_decode
        check = imagecodecs.brotli_check
        level = 11
        encoded = brotli.compress(data)
    elif codec == 'zopfli':
        if not imagecodecs.ZOPFLI or zopfli is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.zopfli_encode
        decode = imagecodecs.zopfli_decode
        check = imagecodecs.zopfli_check
        level = 1
        c = zopfli.ZopfliCompressor(zopfli.ZOPFLI_FORMAT_ZLIB)
        encoded = c.compress(data) + c.flush()
    elif codec == 'snappy':
        if not imagecodecs.SNAPPY or snappy is None:
            pytest.skip(f'{codec} missing')
        encode = imagecodecs.snappy_encode
        decode = imagecodecs.snappy_decode
        check = imagecodecs.snappy_check
        level = 1
        encoded = snappy.compress(data)
    else:
        raise ValueError(codec)

    assert check(encoded) in (None, True)

    if func == 'encode':
        size = len(encoded)
        if output == 'new':
            assert encoded == encode(data, level)
        elif output == 'bytearray':
            ret = encode(data, level, out=bytearray)
            assert encoded == ret
        elif output == 'size':
            ret = encode(data, level, out=size)
            assert encoded == ret
        elif output == 'out':
            if codec == 'zstd':
                out = bytearray(max(size, 64))
            # elif codec == 'blosc':
            #     out = bytearray(max(size, 17))  # bug in blosc ?
            elif codec == 'lzf':
                out = bytearray(size + 1)  # bug in liblzf ?
            else:
                out = bytearray(size)
            ret = encode(data, level, out=out)
            assert encoded == out[:size]
            assert encoded == ret
        elif output == 'excess':
            out = bytearray(size + 1021)
            ret = encode(data, level, out=out)
            if codec == 'blosc':
                # pytest.xfail("blosc output depends on output size")
                assert data == decode(ret)
            else:
                assert ret == out[:size]
                assert encoded == ret
        elif output == 'trunc':
            size = max(0, size - 1)
            out = bytearray(size)
            if size == 0 and codec == 'bitshuffle':
                encode(data, level, out=out) == b''
            else:
                with pytest.raises(RuntimeError):
                    encode(data, level, out=out)
        else:
            raise ValueError(output)
    elif func == 'decode':
        size = len(data)
        if output == 'new':
            assert data == decode(encoded)
        elif output == 'bytearray':
            ret = decode(encoded, out=bytearray)
            assert data == ret
        elif output == 'size':
            ret = decode(encoded, out=size)
            assert data == ret
        elif output == 'out':
            out = bytearray(size)
            ret = decode(encoded, out=out)
            assert data == out
            assert data == ret
        elif output == 'excess':
            out = bytearray(size + 1021)
            ret = decode(encoded, out=out)
            assert data == out[:size]
            assert data == ret
        elif output == 'trunc':
            size = max(0, size - 1)
            out = bytearray(size)
            if length == 0 or codec in ('bz2', 'lzma'):
                decode(encoded, out=out)
                assert data[:size] == out
            else:
                # most codecs don't support truncated output
                with pytest.raises(RuntimeError):
                    decode(encoded, out=out)
        else:
            raise ValueError(output)
    else:
        raise ValueError(func)


@pytest.mark.skipif(not imagecodecs.BITSHUFFLE, reason='bitshuffle missing')
@pytest.mark.parametrize('dtype', ['bytes', 'ndarray'])
@pytest.mark.parametrize('itemsize', [1, 2, 4, 8])
@pytest.mark.parametrize('blocksize', [0, 8, 64])
def test_bitshuffle_roundtrip(dtype, itemsize, blocksize):
    """Test Bitshuffle codec."""
    encode = imagecodecs.bitshuffle_encode
    decode = imagecodecs.bitshuffle_decode
    if dtype == 'bytes':
        data = numpy.random.randint(255, size=1024, dtype='uint8').tobytes()
    else:
        data = numpy.random.randint(255, size=1024, dtype=f'u{itemsize}')
        data.shape = 2, 4, 128
    encoded = encode(data, itemsize=itemsize, blocksize=blocksize)
    decoded = decode(encoded, itemsize=itemsize, blocksize=blocksize)
    if dtype == 'bytes':
        assert data == decoded
    else:
        assert_array_equal(data, decoded)


@pytest.mark.skipif(not imagecodecs.BLOSC, reason='blosc missing')
@pytest.mark.parametrize('numthreads', [1, 6])
@pytest.mark.parametrize('level', [None, 1])
@pytest.mark.parametrize('shuffle', ['noshuffle', 'shuffle', 'bitshuffle'])
@pytest.mark.parametrize('compressor', ['blosclz', 'lz4', 'lz4hc', 'snappy',
                                        'zlib', 'zstd'])
def test_blosc_roundtrip(compressor, shuffle, level, numthreads):
    """Test Blosc codec."""
    encode = imagecodecs.blosc_encode
    decode = imagecodecs.blosc_decode
    data = numpy.random.randint(255, size=2021, dtype='uint8').tobytes()
    encoded = encode(data, level=level, compressor=compressor,
                     shuffle=shuffle, numthreads=numthreads)
    decoded = decode(encoded, numthreads=numthreads)
    assert data == decoded


# test data from libaec https://gitlab.dkrz.de/k202009/libaec/tree/master/data
AEC_TEST_DIR = osp.join(TEST_DIR, 'libaec/121B2TestData')

AEC_TEST_OPTIONS = list(
    osp.split(f)[-1][5:-3] for f in glob.glob(osp.join(
        AEC_TEST_DIR, 'AllOptions', '*.rz')))

AEC_TEST_EXTENDED = list(
    osp.split(f)[-1][:-3] for f in glob.glob(osp.join(
        AEC_TEST_DIR, 'ExtendedParameters', '*.rz')))


@pytest.mark.skipif(not imagecodecs.AEC, reason='aec missing')
@pytest.mark.parametrize('dtype', ['bytes', 'numpy'])
@pytest.mark.parametrize('name', AEC_TEST_EXTENDED)
def test_aec_extended(name, dtype):
    """Test AEC codec with libaec ExtendedParameters."""
    if (
        name == 'sar32bit.j16.r256' and
        not (IS_CG or os.environ.get('AEC_TEST_EXTENDED', False))
    ):
        pytest.xfail('aec extension not built with ENABLE_RSI_PADDING')

    encode = imagecodecs.aec_encode
    decode = imagecodecs.aec_decode

    size = 512 * 512 * 4
    bitspersample = 32
    flags = imagecodecs.AEC.DATA_PREPROCESS | imagecodecs.AEC.PAD_RSI

    matches = re.search(r'j(\d+)\.r(\d+)', name).groups()
    blocksize = int(matches[0])
    rsi = int(matches[1])

    filename = osp.join(AEC_TEST_DIR, 'ExtendedParameters', f'{name}.rz')
    with open(filename, 'rb') as fh:
        rz = fh.read()

    filename = osp.join(AEC_TEST_DIR, 'ExtendedParameters',
                        '{}.dat'.format(name.split('.')[0]))
    if dtype == 'bytes':
        with open(filename, 'rb') as fh:
            dat = fh.read()
        out = size
    else:
        dat = numpy.fromfile(filename, 'uint32').reshape(512, 512)
        out = numpy.empty_like(dat)

    # decode
    decoded = decode(rz, bitspersample=bitspersample, flags=flags,
                     blocksize=blocksize, rsi=rsi, out=out)
    if dtype == 'bytes':
        assert decoded == dat
    else:
        pass

    # roundtrip
    if dtype == 'bytes':
        encoded = encode(dat, bitspersample=bitspersample, flags=flags,
                         blocksize=blocksize, rsi=rsi)
        # fails with AEC_DATA_ERROR if libaec wasn't built with libaec.diff
        decoded = decode(encoded, bitspersample=bitspersample, flags=flags,
                         blocksize=blocksize, rsi=rsi, out=size)
        assert decoded == dat
    else:
        encoded = encode(dat, flags=flags, blocksize=blocksize, rsi=rsi)
        # fails with AEC_DATA_ERROR if libaec wasn't built with libaec.diff
        decoded = decode(encoded, flags=flags, blocksize=blocksize, rsi=rsi,
                         out=out)
        assert_array_equal(decoded, out)


@pytest.mark.skipif(not imagecodecs.AEC, reason='aec missing')
@pytest.mark.parametrize('name', AEC_TEST_OPTIONS)
def test_aec_options(name):
    """Test AEC codec with libaec 121B2TestData."""
    encode = imagecodecs.aec_encode
    decode = imagecodecs.aec_decode

    rsi = 128
    blocksize = 16
    flags = imagecodecs.AEC.DATA_PREPROCESS
    if 'restricted' in name:
        flags |= imagecodecs.AEC.RESTRICTED
    matches = re.search(r'p(\d+)n(\d+)', name).groups()
    size = int(matches[0])
    bitspersample = int(matches[1])

    if bitspersample > 8:
        size *= 2
    if bitspersample > 16:
        size *= 2

    filename = osp.join(AEC_TEST_DIR, 'AllOptions', f'test_{name}.rz')
    with open(filename, 'rb') as fh:
        rz = fh.read()

    filename = filename.replace('.rz', '.dat'
                                ).replace('-basic', ''
                                          ).replace('-restricted', '')
    with open(filename, 'rb') as fh:
        dat = fh.read()
    out = size

    # decode
    decoded = decode(rz, bitspersample=bitspersample, flags=flags,
                     blocksize=blocksize, rsi=rsi, out=out)
    assert decoded == dat

    # roundtrip
    encoded = encode(dat, bitspersample=bitspersample, flags=flags,
                     blocksize=blocksize, rsi=rsi)
    decoded = decode(encoded, bitspersample=bitspersample, flags=flags,
                     blocksize=blocksize, rsi=rsi, out=out)
    assert decoded == dat


@pytest.mark.parametrize('optimize', [False, True])
@pytest.mark.parametrize('smoothing', [0, 25])
@pytest.mark.parametrize('subsampling', ['444', '422', '420', '411', '440'])
@pytest.mark.parametrize('itype', ['rgb', 'rgba', 'gray'])
@pytest.mark.parametrize('codec', ['jpeg8', 'jpeg12'])
def test_jpeg_encode(codec, itype, subsampling, smoothing, optimize):
    """Test various JPEG encode options."""
    # general and default options are tested in test_image_roundtrips
    if codec == 'jpeg8':
        if not imagecodecs.JPEG8:
            pytest.skip('jpeg8 missing')
        dtype = 'uint8'
        decode = imagecodecs.jpeg8_decode
        encode = imagecodecs.jpeg8_encode
        atol = 24
    elif codec == 'jpeg12':
        if not imagecodecs.JPEG12:
            pytest.skip('jpeg12 missing')
        if not optimize:
            pytest.xfail('jpeg12 fails without optimize')
        dtype = 'uint16'
        decode = imagecodecs.jpeg12_decode
        encode = imagecodecs.jpeg12_encode
        atol = 24 * 16
    else:
        raise ValueError(codec)

    dtype = numpy.dtype(dtype)
    data = image_data(itype, dtype)
    data = data[:32, :16].copy()  # make divisable by subsamples

    encoded = encode(data, level=95, subsampling=subsampling,
                     smoothing=smoothing, optimize=optimize)
    decoded = decode(encoded)

    if itype == 'gray':
        decoded = decoded.reshape(data.shape)

    assert_allclose(data, decoded, atol=atol)


@pytest.mark.skipif(not imagecodecs.JPEG8, reason='jpeg8 missing')
@pytest.mark.parametrize('output', ['new', 'out'])
def test_jpeg8_decode(output):
    """Test JPEG 8-bit decoder with separate tables."""
    decode = imagecodecs.jpeg8_decode
    data = readfile('bytes.jpeg8.bin')
    tables = readfile('bytes.jpeg8_tables.bin')

    if output == 'new':
        decoded = decode(data, tables=tables)
    elif output == 'out':
        decoded = numpy.empty_like(BYTESIMG)
        decode(data, tables=tables, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(BYTESIMG.size * BYTESIMG.itemsize)
        decoded = decode(data, out=decoded)
    assert_array_equal(BYTESIMG, decoded)


@pytest.mark.skipif(not imagecodecs.JPEG12, reason='jpeg12 missing')
@pytest.mark.parametrize('output', ['new', 'out', 'bytearray'])
def test_jpeg12_decode(output):
    """Test JPEG 12-bit decoder with separate tables."""
    decode = imagecodecs.jpeg12_decode
    data = readfile('words.jpeg12.bin')
    tables = readfile('words.jpeg12_tables.bin')

    if output == 'new':
        decoded = decode(data, tables=tables)
    elif output == 'out':
        decoded = numpy.empty_like(WORDSIMG)
        decode(data, tables=tables, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(WORDSIMG.size * WORDSIMG.itemsize)
        decoded = decode(data, out=decoded)

    assert numpy.max(numpy.abs(WORDSIMG.astype('int32') -
                               decoded.astype('int32'))) < 2


@pytest.mark.skipif(not imagecodecs.JPEGSOF3, reason='jpegsof3 missing')
@pytest.mark.parametrize('output', ['new', 'out', 'bytearray'])
@pytest.mark.parametrize('fname', ['gray8.sof3.jpg', 'gray16.sof3.jpg'])
def test_jpegsof3(fname, output):
    """Test JPEG SOF3 decoder with 8 and 16-bit images."""
    decode = imagecodecs.jpegsof3_decode

    shape = 535, 800
    if fname == 'gray8.sof3.jpg':
        dtype = 'uint8'
        value = 75
        memmap = True  # test read-only, jpegsof3_decode requires writable
    elif fname == 'gray16.sof3.jpg':
        dtype = 'uint16'
        value = 19275
        memmap = False

    data = readfile(fname, memmap=memmap)

    assert imagecodecs.jpegsof3_check(data) in (None, True)

    if output == 'new':
        decoded = decode(data)
    elif output == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(data, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(535 * 800 * numpy.dtype(dtype).itemsize)
        decoded = decode(data, out=decoded)

    assert decoded.shape == shape
    assert decoded.dtype == dtype
    assert decoded[500, 600] == value


@pytest.mark.skipif(not imagecodecs.JPEGXR, reason='jpegxr missing')
@pytest.mark.parametrize('output', ['new', 'out', 'bytearray'])
def test_jpegxr_decode(output):
    """Test JPEG XR decoder with RGBA32 image."""
    decode = imagecodecs.jpegxr_decode
    image = readfile('rgba32.jxr.bin')
    image = numpy.frombuffer(image, dtype='uint8').reshape(100, 100, -1)
    data = readfile('rgba32.jxr')

    assert imagecodecs.jpegxr_check(data) in (None, True)

    if output == 'new':
        decoded = decode(data)
    elif output == 'out':
        decoded = numpy.empty_like(image)
        decode(data, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(image.size * image.itemsize)
        decoded = decode(data, out=decoded)
    assert_array_equal(image, decoded)


@pytest.mark.skipif(not imagecodecs.JPEG2K, reason='jpeg2k missing')
@pytest.mark.parametrize('output', ['new', 'out', 'bytearray'])
def test_jpeg2k_int8_4bit(output):
    """Test JPEG 2000 decoder with int8, 4-bit image."""
    decode = imagecodecs.jpeg2k_decode
    data = readfile('int8_4bit.j2k')
    dtype = 'int8'
    shape = 256, 256

    assert imagecodecs.jpeg2k_check(data)

    if output == 'new':
        decoded = decode(data, verbose=2)
    elif output == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(data, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(shape[0] * shape[1])
        decoded = decode(data, out=decoded)

    assert decoded.dtype == dtype
    assert decoded.shape == shape
    assert decoded[0, 0] == -6
    assert decoded[-1, -1] == 2


@pytest.mark.skipif(not imagecodecs.JPEG2K, reason='jpeg2k missing')
def test_jpeg2k_ycbc():
    """Test JPEG 2000 decoder with subsampling."""
    decode = imagecodecs.jpeg2k_decode
    data = readfile('ycbc.j2k')

    assert imagecodecs.jpeg2k_check(data)

    decoded = decode(data, verbose=2)
    assert decoded.dtype == 'uint8'
    assert decoded.shape == (256, 256, 3)
    assert tuple(decoded[0, 0]) == (243, 243, 240)
    assert tuple(decoded[-1, -1]) == (0, 0, 0)


@pytest.mark.skipif(not imagecodecs.JPEGXL, reason='jpegls missing')
@pytest.mark.parametrize('output', ['new', 'out', 'bytearray'])
def test_jpegls_decode(output):
    """Test JPEG LS decoder with RGBA32 image."""
    decode = imagecodecs.jpegls_decode
    data = readfile('rgba.u1.jls')
    dtype = 'uint8'
    shape = 32, 31, 4

    assert imagecodecs.jpegls_check(data) in (None, True)

    if output == 'new':
        decoded = decode(data)
    elif output == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(data, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(shape[0] * shape[1] * shape[2])
        decoded = decode(data, out=decoded)

    assert decoded.dtype == dtype
    assert decoded.shape == shape
    assert decoded[25, 25, 1] == 97
    assert decoded[-1, -1, -1] == 63


@pytest.mark.skipif(not imagecodecs.JPEGXL, reason='jpegxl missing')
@pytest.mark.parametrize('output', ['new', 'out', 'bytearray'])
def test_jpegxl_decode(output):
    """Test JPEG XL decoder with RGBA32 image."""
    decode = imagecodecs.jpegxl_decode
    data = readfile('rgba.u1.jxl')
    dtype = 'uint8'
    shape = 32, 31, 4

    assert imagecodecs.jpegxl_check(data) in (None, True)

    if output == 'new':
        decoded = decode(data)
    elif output == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(data, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(shape[0] * shape[1] * shape[2])
        decoded = decode(data, out=decoded)

    assert decoded.dtype == dtype
    assert decoded.shape == shape
    assert decoded[25, 25, 1] == 100
    assert decoded[-1, -1, -1] == 81


@pytest.mark.skipif(not imagecodecs.JPEGXL, reason='jpegxl missing')
def test_jpegxl_encode_jpeg():
    """Test JPEG XL encoder with JPEG input."""
    encode = imagecodecs.jpegxl_encode
    decode = imagecodecs.jpegxl_decode
    jpg = readfile('rgba.u1.jpg')
    jxl = readfile('rgba.u1.jxl')

    assert imagecodecs.jpegxl_check(jpg) in (None, True)
    assert imagecodecs.jpegxl_check(jxl) in (None, True)

    encoded = encode(jpg)
    assert encoded == jxl

    decoded = decode(encoded)
    assert decoded.dtype == 'uint8'
    assert decoded.shape == (32, 31, 4)
    assert decoded[25, 25, 1] == 100
    assert decoded[-1, -1, -1] == 81


@pytest.mark.skipif(not imagecodecs.WEBP, reason='webp missing')
@pytest.mark.parametrize('output', ['new', 'out', 'bytearray'])
def test_webp_decode(output):
    """Test WebpP  decoder with RGBA32 image."""
    decode = imagecodecs.webp_decode
    data = readfile('rgba.u1.webp')
    dtype = 'uint8'
    shape = 32, 31, 4

    assert imagecodecs.webp_check(data)

    if output == 'new':
        decoded = decode(data)
    elif output == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(data, out=decoded)
    elif output == 'bytearray':
        decoded = bytearray(shape[0] * shape[1] * shape[2])
        decoded = decode(data, out=decoded)

    assert decoded.dtype == dtype
    assert decoded.shape == shape
    assert decoded[25, 25, 1] == 94  # lossy
    assert decoded[-1, -1, -1] == 63


@pytest.mark.skipif(not imagecodecs.ZFP, reason='zfp missing')
@pytest.mark.parametrize('execution', [None, 'omp'])
@pytest.mark.parametrize('mode', [(None, None), ('p', None)])  # ('r', 24)
@pytest.mark.parametrize('deout', ['new', 'out', 'bytearray'])  # 'view',
@pytest.mark.parametrize('enout', ['new', 'out', 'bytearray'])
@pytest.mark.parametrize('itype', ['rgba', 'view', 'gray', 'line'])
@pytest.mark.parametrize('dtype', ['float32', 'float64', 'int32', 'int64'])
def test_zfp(dtype, itype, enout, deout, mode, execution):
    """Test ZFP codec."""
    if execution == 'omp' and os.environ.get('SKIP_OMP', False):
        pytest.skip('omp test skip because of enviroment variable')
    decode = imagecodecs.zfp_decode
    encode = imagecodecs.zfp_encode
    mode, level = mode
    dtype = numpy.dtype(dtype)
    itemsize = dtype.itemsize
    data = image_data(itype, dtype)
    shape = data.shape

    kwargs = dict(mode=mode, level=level, execution=execution)
    encoded = encode(data, **kwargs)

    assert imagecodecs.zfp_check(encoded)

    if enout == 'new':
        pass
    elif enout == 'out':
        encoded = numpy.empty(len(encoded), 'uint8')
        encode(data, out=encoded, **kwargs)
    elif enout == 'bytearray':
        encoded = bytearray(len(encoded))
        encode(data, out=encoded, **kwargs)

    if deout == 'new':
        decoded = decode(encoded)
    elif deout == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(encoded, out=decoded)
    elif deout == 'view':
        temp = numpy.empty((shape[0] + 5, shape[1] + 5, shape[2]), dtype)
        decoded = temp[2:2 + shape[0], 3:3 + shape[1], :]
        decode(encoded, out=decoded)
    elif deout == 'bytearray':
        decoded = bytearray(shape[0] * shape[1] * shape[2] * itemsize)
        decoded = decode(encoded, out=decoded)
        decoded = numpy.asarray(decoded, dtype=dtype).reshape(shape)

    if dtype.char == 'f':
        atol = 1e-6
    else:
        atol = 20
    assert_allclose(data, decoded, atol=atol, rtol=0)


@pytest.mark.skipif(not imagecodecs.LERC, reason='lerc missing')
# @pytest.mark.parametrize('version', [None, 3])
@pytest.mark.parametrize('level', [None, 0.02])
@pytest.mark.parametrize('planarconfig', [None, 'separate'])
@pytest.mark.parametrize('deout', ['new', 'out', 'bytearray'])
@pytest.mark.parametrize('enout', ['new', 'out', 'bytearray'])
@pytest.mark.parametrize('itype', ['gray', 'rgb', 'rgba', 'channels', 'stack'])
@pytest.mark.parametrize('dtype', ['uint8', 'int8', 'uint16', 'int32',
                                   'float32', 'float64'])
def test_lerc(dtype, itype, enout, deout, planarconfig, level, version=None):
    """Test LERC codec."""
    if version is not None and version < 4 and itype != 'gray':
        pytest.xfail("lerc version doesn't support these cases")
    decode = imagecodecs.lerc_decode
    encode = imagecodecs.lerc_encode
    dtype = numpy.dtype(dtype)
    itemsize = dtype.itemsize
    data = image_data(itype, dtype)
    shape = data.shape
    if level is not None and dtype.kind != 'f':
        level = level * 256

    kwargs = dict(level=level, version=version, planarconfig=planarconfig)
    encoded = encode(data, **kwargs)

    assert imagecodecs.lerc_check(encoded)

    if enout == 'new':
        pass
    elif enout == 'out':
        encoded = numpy.empty(len(encoded), 'uint8')
        encode(data, out=encoded, **kwargs)
    elif enout == 'bytearray':
        encoded = bytearray(len(encoded))
        encode(data, out=encoded, **kwargs)

    if deout == 'new':
        decoded = decode(encoded)
    elif deout == 'out':
        decoded = numpy.empty(shape, dtype)
        if planarconfig is None:
            out = numpy.squeeze(decoded)
        else:
            out = decoded
        decode(encoded, out=out)
    elif deout == 'bytearray':
        decoded = bytearray(shape[0] * shape[1] * shape[2] * itemsize)
        decoded = decode(encoded, out=decoded)
        decoded = numpy.asarray(decoded, dtype=dtype).reshape(shape)

    if itype == 'gray':
        decoded = decoded.reshape(shape)

    if level is None:
        level = 0.00001 if dtype.kind == 'f' else 0
    assert_allclose(data, decoded, atol=level, rtol=0)


@pytest.mark.skipif(not imagecodecs.JPEGXR, reason='jpegxr missing')
@pytest.mark.parametrize('level', [None, 90, 0.4])
@pytest.mark.parametrize('deout', ['new', 'out', 'bytearray'])  # 'view',
@pytest.mark.parametrize('enout', ['new', 'out', 'bytearray'])
@pytest.mark.parametrize('itype', [
    'gray uint8', 'gray uint16', 'gray float16', 'gray float32',
    'rgb uint8', 'rgb uint16', 'rgb float16', 'rgb float32',
    'rgba uint8', 'rgba uint16', 'rgba float16', 'rgba float32',
    'channels uint8', 'channelsa uint8', 'channels uint16', 'channelsa uint16',
    'cmyk uint8', 'cmyka uint8'])
def test_jpegxr(itype, enout, deout, level):
    """Test JPEG XR codec."""
    decode = imagecodecs.jpegxr_decode
    encode = imagecodecs.jpegxr_encode
    itype, dtype = itype.split()
    dtype = numpy.dtype(dtype)
    itemsize = dtype.itemsize
    data = image_data(itype, dtype)
    shape = data.shape

    kwargs = dict(level=level)
    if itype.startswith('cmyk'):
        kwargs['photometric'] = 'cmyk'
    if itype.endswith('a'):
        kwargs['hasalpha'] = True
    print(data.shape, data.dtype, data.strides)
    encoded = encode(data, **kwargs)

    assert imagecodecs.jpegxr_check(encoded) in (None, True)

    if enout == 'new':
        pass
    elif enout == 'out':
        encoded = numpy.empty(len(encoded), 'uint8')
        encode(data, out=encoded, **kwargs)
    elif enout == 'bytearray':
        encoded = bytearray(len(encoded))
        encode(data, out=encoded, **kwargs)

    if deout == 'new':
        decoded = decode(encoded)
    elif deout == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(encoded, out=numpy.squeeze(decoded))
    elif deout == 'view':
        temp = numpy.empty((shape[0] + 5, shape[1] + 5, shape[2]), dtype)
        decoded = temp[2:2 + shape[0], 3:3 + shape[1], :]
        decode(encoded, out=numpy.squeeze(decoded))
    elif deout == 'bytearray':
        decoded = bytearray(shape[0] * shape[1] * shape[2] * itemsize)
        decoded = decode(encoded, out=decoded)
        decoded = numpy.asarray(decoded, dtype=dtype).reshape(shape)

    if itype == 'gray':
        decoded = decoded.reshape(shape)

    if level is None:
        atol = 0.00001 if dtype.kind == 'f' else 1
    if level == 90:
        atol = 0.005 if dtype.kind == 'f' else 8 if dtype == 'uint8' else 12
    else:
        atol = 0.1 if dtype.kind == 'f' else 64 if dtype == 'uint8' else 700
    assert_allclose(data, decoded, atol=atol, rtol=0)


@pytest.mark.parametrize('level', [None, 5, -1])
@pytest.mark.parametrize('deout', ['new', 'out', 'view', 'bytearray'])
@pytest.mark.parametrize('enout', ['new', 'out', 'bytearray'])
@pytest.mark.parametrize('itype', ['rgb', 'rgba', 'view', 'gray', 'graya'])
@pytest.mark.parametrize('dtype', ['uint8', 'uint16'])
@pytest.mark.parametrize('codec', [
    'webp', 'png', 'jpeg8', 'jpeg12', 'jpegls', 'jpegxl', 'jpegxr', 'jpeg2k'])
def test_image_roundtrips(codec, dtype, itype, enout, deout, level):
    """Test various image codecs."""
    if codec == 'jpeg8':
        if not imagecodecs.JPEG8:
            pytest.skip(f'{codec} missing')
        if itype in ('view', 'graya') or deout == 'view' or dtype == 'uint16':
            pytest.xfail("jpeg8 doesn't support these cases")
        decode = imagecodecs.jpeg8_decode
        encode = imagecodecs.jpeg8_encode
        check = imagecodecs.jpeg8_check
        atol = 24
        if level:
            level += 95
    elif codec == 'jpeg12':
        if not imagecodecs.JPEG12:
            pytest.skip(f'{codec} missing')
        if itype in ('view', 'graya') or deout == 'view' or dtype == 'uint8':
            pytest.xfail("jpeg12 doesn't support these cases")
        decode = imagecodecs.jpeg12_decode
        encode = imagecodecs.jpeg12_encode
        check = imagecodecs.jpeg12_check
        atol = 24 * 16
        if level:
            level += 95
    elif codec == 'jpegls':
        if not imagecodecs.JPEGXL:
            pytest.skip(f'{codec} missing')
        if itype in ('view', 'graya') or deout == 'view':
            pytest.xfail("jpegls doesn't support these cases")
        decode = imagecodecs.jpegls_decode
        encode = imagecodecs.jpegls_encode
        check = imagecodecs.jpegls_check
    elif codec == 'webp':
        if not imagecodecs.WEBP:
            pytest.skip(f'{codec} missing')
        decode = imagecodecs.webp_decode
        encode = imagecodecs.webp_encode
        check = imagecodecs.webp_check
        if dtype != 'uint8' or itype.startswith('gray'):
            pytest.xfail("webp doesn't support these cases")
    elif codec == 'png':
        if not imagecodecs.PNG:
            pytest.skip(f'{codec} missing')
        decode = imagecodecs.png_decode
        encode = imagecodecs.png_encode
        check = imagecodecs.png_check
    elif codec == 'jpeg2k':
        if not imagecodecs.JPEG2K:
            pytest.skip(f'{codec} missing')
        if itype == 'view' or deout == 'view':
            pytest.xfail("jpeg2k doesn't support these cases")
        decode = imagecodecs.jpeg2k_decode
        encode = imagecodecs.jpeg2k_encode
        check = imagecodecs.jpeg2k_check
        if level:
            level += 95
    elif codec == 'jpegxl':
        if not imagecodecs.JPEGXL:
            pytest.skip(f'{codec} missing')
        if itype in ('view', 'graya') or deout == 'view' or dtype == 'uint16':
            pytest.xfail("jpegxl doesn't support these cases")
        decode = imagecodecs.jpegxl_decode
        encode = imagecodecs.jpegxl_encode
        check = imagecodecs.jpegxl_check
        atol = 24
        if level:
            level += 95
    elif codec == 'jpegxr':
        if not imagecodecs.JPEGXR:
            pytest.skip(f'{codec} missing')
        if itype == 'graya' or deout == 'view':
            pytest.xfail("jpegxr doesn't support these cases")
        decode = imagecodecs.jpegxr_decode
        encode = imagecodecs.jpegxr_encode
        check = imagecodecs.jpegxr_check
        atol = 10
        if level:
            level = (level + 95) / 100
    else:
        raise ValueError(codec)

    dtype = numpy.dtype(dtype)
    itemsize = dtype.itemsize
    data = image_data(itype, dtype)
    shape = data.shape

    if enout == 'new':
        encoded = encode(data, level=level)
    elif enout == 'out':
        encoded = numpy.empty(2 * shape[0] * shape[1] * shape[2] * itemsize,
                              'uint8')
        ret = encode(data, level=level, out=encoded)
        if codec == 'jpegxl':
            # Brunsli doesn't like extra bytes
            encoded = encoded[:len(ret)]
    elif enout == 'bytearray':
        encoded = bytearray(2 * shape[0] * shape[1] * shape[2] * itemsize)
        ret = encode(data, level=level, out=encoded)
        if codec == 'jpegxl':
            # Brunsli doesn't like extra bytes
            encoded = encoded[:len(ret)]

    if enout != 'out':
        assert check(encoded) in (None, True)

    if deout == 'new':
        decoded = decode(encoded)
    elif deout == 'out':
        decoded = numpy.empty(shape, dtype)
        decode(encoded, out=numpy.squeeze(decoded))
    elif deout == 'view':
        temp = numpy.empty((shape[0] + 5, shape[1] + 5, shape[2]), dtype)
        decoded = temp[2:2 + shape[0], 3:3 + shape[1], :]
        decode(encoded, out=numpy.squeeze(decoded))
    elif deout == 'bytearray':
        decoded = bytearray(shape[0] * shape[1] * shape[2] * itemsize)
        decoded = decode(encoded, out=decoded)
        decoded = numpy.asarray(decoded, dtype=dtype).reshape(shape)

    if itype == 'gray':
        decoded = decoded.reshape(shape)

    if codec == 'webp' and (level != -1 or itype == 'rgba'):
        # RGBA roundtip doesn't work for A=0
        assert_allclose(data, decoded, atol=255)
    elif codec in ('jpeg8', 'jpeg12', 'jpegxl', 'jpegxr'):
        assert_allclose(data, decoded, atol=atol)
    elif codec == 'jpegls' and level == 5:
        assert_allclose(data, decoded, atol=6)
    else:
        assert_array_equal(data, decoded, verbose=True)


@pytest.mark.skipif(not imagecodecs.GIF, reason='GIF missing')
@pytest.mark.parametrize('deout', ['new', 'out', 'bytearray'])  # 'view'
@pytest.mark.parametrize('enout', ['new', 'out', 'bytearray'])
@pytest.mark.parametrize('itype', ['gray', 'stack'])
@pytest.mark.parametrize('index', [None, 0])
def test_gif_roundtrips(index, itype, enout, deout):
    """Test GIF codec."""
    decode = imagecodecs.gif_decode
    encode = imagecodecs.gif_encode

    dtype = numpy.dtype('uint8')
    data = numpy.squeeze(image_data(itype, dtype))
    if index == 0 and itype == 'stack':
        shaped = data.shape[1:] + (3, )
    else:
        shaped = data.shape + (3, )
    sized = data.size * 3

    if enout == 'new':
        encoded = encode(data)
    elif enout == 'out':
        encoded = numpy.empty(2 * data.size, 'uint8')
        encode(data, out=encoded)
    elif enout == 'bytearray':
        encoded = bytearray(2 * data.size)
        encode(data, out=encoded)

    assert imagecodecs.gif_check(encoded)

    if deout == 'new':
        decoded = decode(encoded, index=index)
    elif deout == 'out':
        decoded = numpy.empty(shaped, dtype)
        decode(encoded, index=index, out=numpy.squeeze(decoded))
    elif deout == 'bytearray':
        decoded = bytearray(sized)
        decoded = decode(encoded, index=index, out=decoded)
        decoded = numpy.asarray(decoded, dtype=dtype).reshape(shaped)

    if index == 0 and itype == 'stack':
        data = data[index]
    assert_array_equal(data, decoded[..., 1], verbose=True)


@pytest.mark.skipif(not imagecodecs.PNG, reason='png missing')
def test_png_rgba_palette():
    """Test decoding indexed PNG with transparency."""
    png = readfile('rgba.u1.pal.png')
    image = imagecodecs.png_decode(png)
    assert tuple(image[6, 15]) == (255, 255, 255, 0)
    assert tuple(image[6, 16]) == (141, 37, 52, 255)


TIFF_TEST_DIR = osp.join(TEST_DIR, 'tiff/')
TIFF_FILES = list(osp.split(f)[-1][:-4]
                  for f in glob.glob(osp.join(TIFF_TEST_DIR, '*.tif')))


@pytest.mark.skipif(not imagecodecs.TIFF, reason='tiff missing')
@pytest.mark.skipif(tifffile is None, reason='tifffile missing')
@pytest.mark.parametrize('asrgb', [False, True])
@pytest.mark.parametrize('name', TIFF_FILES)
def test_tiff_files(name, asrgb):
    """Test TIFF decode with existing files against tifffile."""
    decode = imagecodecs.tiff_decode
    if 'depth' in name or 'jpeg.u2' in name or (
        not IS_CG and ('webp' in name or 'zstd' in name or 'lzma' in name)
    ):
        pytest.xfail('not supported by libtiff or tiff_decode')

    filename = osp.join(TIFF_TEST_DIR, f'{name}.tif')
    with open(filename, 'rb') as fh:
        encoded = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)

    assert imagecodecs.tiff_check(encoded)

    if asrgb:
        if (
            'b1' in name or 'u1' in name or 'u2' in name or 'i1' in name or
            'i2' in name
        ):
            decoded = decode(encoded, index=0, asrgb=1, verbose=1)
        else:
            with pytest.raises(imagecodecs.TiffError):
                decoded = decode(encoded, index=0, asrgb=1, verbose=1)
        return

    if 'b1' in name:
        pytest.xfail('not supported yet')
    data = tifffile.imread(filename)
    decoded = decode(encoded, index=None, verbose=1)
    if 'movie' in name:
        # libtiff only reads 2**16 images
        assert data.shape[0] == 65568
        data = data[:65535]
    elif 'jpeg' in name:
        # tiff_decode returns RGBA for jpeg, tifffile returns RGB
        decoded = decoded[..., :3]
    assert_array_equal(data, decoded)


@pytest.mark.skipif(not imagecodecs.TIFF, reason='tiff missing')
@pytest.mark.skipif(tifffile is None, reason='tifffile missing')
@pytest.mark.parametrize('index', [0, 3, 10, 65536, None, list, slice])
def test_tiff_index(index):
    """Test TIFF decoder index arguments."""
    filename = osp.join(TIFF_TEST_DIR, 'gray.series.u1.tif')
    with open(filename, 'rb') as fh:
        encoded = fh.read()
    if index == 10 or index == 65536:
        with pytest.raises((IndexError, OverflowError)):
            decoded = imagecodecs.tiff_decode(encoded, index=index)
    elif index == list:
        data = tifffile.imread(filename, series=1)
        decoded = imagecodecs.tiff_decode(encoded, index=[1, 3, 5, 7])
        assert_array_equal(data, decoded)
    elif index == slice:
        for index in (slice(None), slice(1, None, None), slice(1, 3, None)):
            with pytest.raises((IndexError, ValueError)):
                decoded = imagecodecs.tiff_decode(encoded, index=index)
        data = tifffile.imread(filename, series=1)
        for index in (slice(1, None, 2), slice(1, 8, 2)):
            decoded = imagecodecs.tiff_decode(encoded, index=index)
            assert_array_equal(data, decoded)
    elif index is None:
        data = tifffile.imread(filename)
        decoded = imagecodecs.tiff_decode(encoded, index=None)
        assert_array_equal(data, decoded)
    else:
        data = tifffile.imread(filename, key=index)
        decoded = imagecodecs.tiff_decode(encoded, index=index)
        assert_array_equal(data, decoded)


@pytest.mark.skipif(not imagecodecs.TIFF, reason='')
@pytest.mark.skipif(tifffile is None, reason='tifffile missing')
def test_tiff_asrgb():
    """Test TIFF decoder asrgb arguments."""
    filename = osp.join(TIFF_TEST_DIR, 'gray.series.u1.tif')
    with open(filename, 'rb') as fh:
        encoded = fh.read()

    data = tifffile.imread(filename, series=0)
    decoded = imagecodecs.tiff_decode(encoded, index=None, asrgb=True)
    assert decoded.shape[-1] == 4
    assert_array_equal(data, decoded[..., 0])

    data = tifffile.imread(filename, series=1)
    decoded = imagecodecs.tiff_decode(encoded, index=[1, 3, 5, 7], asrgb=True)
    assert decoded.shape[-1] == 4
    assert_array_equal(data, decoded[..., :3])


@pytest.mark.skipif(tifffile is None, reason='tifffile module missing')
@pytest.mark.parametrize('dtype', ['u1', 'u2', 'f4'])
@pytest.mark.parametrize('codec', ['deflate', 'lzma', 'zstd', 'packbits'])
def test_tifffile(dtype, codec):
    """Test tifffile compression."""
    if codec == 'deflate' and not imagecodecs.ZLIB:
        # TODO: this should pass in tifffile >= 2020
        pytest.xfail('zlib missing')
    elif codec == 'lzma' and not imagecodecs.LZMA:
        pytest.xfail('lzma missing')
    elif codec == 'zstd' and not imagecodecs.ZSTD:
        pytest.xfail('zstd missing')
    elif codec == 'packbits' and not imagecodecs.PACKBITS:
        pytest.xfail('packbits missing')
    elif codec == 'packbits' and dtype != 'u1':
        pytest.xfail('dtype not supported')

    data = image_data('rgb', dtype)
    with io.BytesIO() as fh:
        tifffile.imwrite(fh, data, compress=codec)
        fh.seek(0)
        image = tifffile.imread(fh)
    assert_array_equal(data, image, verbose=True)


@pytest.mark.skipif(czifile is None, reason='czifile missing')
def test_czifile():
    """Test JpegXR compressed CZI file."""
    fname = datafiles('jpegxr.czi')
    if not osp.exists(fname):
        pytest.skip('large file not included with source distribution')
    if not imagecodecs.JPEGXR:
        pytest.xfail('jpegxr missing')

    with czifile.CziFile(fname) as czi:
        assert czi.shape == (1, 1, 15, 404, 356, 1)
        assert czi.axes == 'BCZYX0'
        # verify data
        data = czi.asarray()
        assert data.flags['C_CONTIGUOUS']
        assert data.shape == (1, 1, 15, 404, 356, 1)
        assert data.dtype == 'uint16'
        assert data[0, 0, 14, 256, 146, 0] == 38086


@pytest.mark.skipif(not imagecodecs.JPEG8, reason='jpeg8 missing')
@pytest.mark.skipif(IS_32BIT, reason='data too large for 32-bit')
def test_jpeg8_large():
    """Test JPEG 8-bit decoder with dimensions > 65000."""
    decode = imagecodecs.jpeg8_decode
    try:
        data = readfile('33792x79872.jpg', memmap=True)
    except OSError:
        pytest.skip('large file not included with source distribution')
    if not IS_WIN:
        pytest.xfail("libjpeg-turbo wasn't compiled with libjpeg-turbo.diff")
        # Jpeg8Error: Empty JPEG image (DNL not supported)

    assert imagecodecs.jpeg8_check(data)

    decoded = decode(data, shape=(33792, 79872))
    assert decoded.shape == (33792, 79872, 3)
    assert decoded.dtype == 'uint8'
    assert tuple(decoded[33791, 79871]) == (204, 195, 180)


###############################################################################

class TempFileName():
    """Temporary file name context manager."""
    def __init__(self, name=None, suffix='', remove=True):
        self.remove = bool(remove)
        if not name:
            self.name = tempfile.NamedTemporaryFile(prefix='test_',
                                                    suffix=suffix).name
        else:
            self.name = osp.join(tempfile.gettempdir(), f'test_{name}{suffix}')

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc_value, traceback):
        if self.remove:
            try:
                os.remove(self.name)
            except Exception:
                pass


def datafiles(pathname, base=None):
    """Return path to data file(s)."""
    if base is None:
        base = osp.dirname(__file__)
    path = osp.join(base, *pathname.split('/'))
    if any(i in path for i in '*?'):
        return glob.glob(path)
    return path


def readfile(fname, memmap=False):
    """Return content of data file."""
    with open(datafiles(fname), 'rb') as fh:
        if memmap:
            data = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        else:
            data = fh.read()
    return data


def image_data(itype, dtype):
    """Return test image array."""
    if itype in ('rgb', 'view'):
        data = DATA[..., [0, 2, 4]]
    elif itype == 'rgba':
        data = DATA[..., [0, 2, 4, -1]]
    elif itype == 'cmyk':
        data = DATA[..., [0, 2, 4, 6]]
    elif itype == 'cmyka':
        data = DATA[..., [0, 2, 4, 6, -1]]
    elif itype == 'gray':
        data = DATA[..., 0:1]
    elif itype == 'graya':
        data = DATA[..., [0, -1]]
    elif itype == 'rrggbbaa':
        data = numpy.moveaxis(DATA[..., [0, 2, 4, -1]], -1, 0)
    elif itype == 'rrggbb':
        data = numpy.moveaxis(DATA[..., [0, 2, 4]], -1, 0)
    elif itype == 'channels':
        data = DATA[..., :-1]
    elif itype == 'channelsa':
        data = DATA[..., :]
    elif itype == 'line':
        data = DATA[0:1, :, 0:1]
    elif itype == 'stack':
        data = numpy.moveaxis(DATA, -1, 0)
    else:
        raise ValueError('itype not found')

    data = data.copy()

    dtype = numpy.dtype(dtype)
    if dtype.kind in 'iu':
        iinfo = numpy.iinfo(dtype)
        if dtype.kind == 'u':
            data *= iinfo.max + 1
        else:
            data *= (iinfo.max - iinfo.max) / 2
            data -= 1.0 / 2.0
        data = numpy.rint(data)
        data = numpy.clip(data, iinfo.min, iinfo.max)
    elif dtype.kind != 'f':
        raise NotImplementedError('dtype not supported')

    data = data.astype(dtype)

    if dtype == 'uint16':
        # 12-bit
        data //= 16

    if itype == 'view':
        shape = data.shape
        temp = numpy.empty((shape[0] + 5, shape[1] + 5, shape[2]), dtype)
        temp[2:2 + shape[0], 3:3 + shape[1], :] = data
        data = temp[2:2 + shape[0], 3:3 + shape[1], :]

    return data


DATA = numpy.load(datafiles('testdata.npy'))  # (32, 31, 9) float64
BYTES = readfile('bytes.bin')
BYTESIMG = numpy.frombuffer(BYTES, 'uint8').reshape(16, 16)
WORDS = readfile('words.bin')
WORDSIMG = numpy.frombuffer(WORDS, 'uint16').reshape(36, 36, 3)

if __name__ == '__main__':
    import warnings
    # warnings.simplefilter('always')  # noqa
    warnings.filterwarnings('ignore', category=ImportWarning)  # noqa
    argv = sys.argv
    argv.append('-vv')
    pytest.main(argv)
