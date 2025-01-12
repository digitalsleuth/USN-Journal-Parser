#!/usr/bin/python3
"""
# Copyright 2017 Adam Witt
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Original Author - Contact: <accidentalassist@gmail.com>
# Updated for Python 3 by Corey Forman <github.com/digitalsleuth>
"""
__author__ = 'Adam Witt / Corey Forman'
__version__ = '5.0.0'
__date__ = '15 July 2022'
__description__ = 'Python 3 script to parse the NTFS USN Journal'


import os
import sys
import json
import struct
import collections
from argparse import ArgumentParser
from datetime import datetime


reasons = collections.OrderedDict()
reasons[0x1] = 'DATA_OVERWRITE'
reasons[0x2] = 'DATA_EXTEND'
reasons[0x4] = 'DATA_TRUNCATION'
reasons[0x10] = 'NAMED_DATA_OVERWRITE'
reasons[0x20] = 'NAMED_DATA_EXTEND'
reasons[0x40] = 'NAMED_DATA_TRUNCATION'
reasons[0x100] = 'FILE_CREATE'
reasons[0x200] = 'FILE_DELETE'
reasons[0x400] = 'EA_CHANGE'
reasons[0x800] = 'SECURITY_CHANGE'
reasons[0x1000] = 'RENAME_OLD_NAME'
reasons[0x2000] = 'RENAME_NEW_NAME'
reasons[0x4000] = 'INDEXABLE_CHANGE'
reasons[0x8000] = 'BASIC_INFO_CHANGE'
reasons[0x10000] = 'HARD_LINK_CHANGE'
reasons[0x20000] = 'COMPRESSION_CHANGE'
reasons[0x40000] = 'ENCRYPTION_CHANGE'
reasons[0x80000] = 'OBJECT_ID_CHANGE'
reasons[0x100000] = 'REPARSE_POINT_CHANGE'
reasons[0x200000] = 'STREAM_CHANGE'
reasons[0x800000] = 'INTEGRITY_CHANGE'
reasons[0x00400000] = 'TRANSACTED_CHANGE'
reasons[0x80000000] = 'CLOSE'


attributes = collections.OrderedDict()
attributes[0x1] = 'READONLY'
attributes[0x2] = 'HIDDEN'
attributes[0x4] = 'SYSTEM'
attributes[0x10] = 'DIRECTORY'
attributes[0x20] = 'ARCHIVE'
attributes[0x40] = 'DEVICE'
attributes[0x80] = 'NORMAL'
attributes[0x100] = 'TEMPORARY'
attributes[0x200] = 'SPARSE_FILE'
attributes[0x400] = 'REPARSE_POINT'
attributes[0x800] = 'COMPRESSED'
attributes[0x1000] = 'OFFLINE'
attributes[0x2000] = 'NOT_CONTENT_INDEXED'
attributes[0x4000] = 'ENCRYPTED'
attributes[0x8000] = 'INTEGRITY_STREAM'
attributes[0x10000] = 'VIRTUAL'
attributes[0x20000] = 'NO_SCRUB_DATA'


sourceInfo = collections.OrderedDict()
sourceInfo[0x1] = 'DATA_MANAGEMENT'
sourceInfo[0x2] = 'AUXILIARY_DATA'
sourceInfo[0x4] = 'REPLICATION_MANAGEMENT'
sourceInfo[0x8] = 'CLIENT_REPLICATION_MANAGEMENT'


def parseUsn(infile, usn):
    recordProperties = [
        'majorVersion',
        'minorVersion',
        'fileReferenceNumber',
        'parentFileReferenceNumber',
        'usn',
        'timestamp',
        'reason',
        'sourceInfo',
        'securityId',
        'fileAttributes',
        'filenameLength',
        'filenameOffset'
    ]
    recordDict = dict(zip(recordProperties, usn))
    recordDict['filename'] = filenameHandler(infile, recordDict)
    recordDict['reason'] = convertAttributes(reasons, recordDict['reason'])
    recordDict['fileAttributes'] = convertAttributes(
        attributes, recordDict['fileAttributes'])
    recordDict['humanTimestamp'] = filetimeToHumanReadable(
        recordDict['timestamp'])
    recordDict['epochTimestamp'] = filetimeToEpoch(recordDict['timestamp'])
    recordDict['timestamp'] = f"{recordDict['timestamp']:016x}"
    recordDict['mftSeqNumber'], recordDict['mftEntryNumber'] = convertFileReference(
        recordDict['fileReferenceNumber'])
    recordDict['pMftSeqNumber'], recordDict['pMftEntryNumber'] = convertFileReference(
        recordDict['parentFileReferenceNumber'])
    reorder = [
        'filename',
        'humanTimestamp',
        'timestamp',
        'epochTimestamp',
        'usn',
        'fileReferenceNumber',
        'parentFileReferenceNumber',
        'reason',
        'fileAttributes',
        'mftSeqNumber',
        'mftEntryNumber',
        'pMftSeqNumber',
        'pMftEntryNumber',
        'filenameLength',
        'filenameOffset',
        'sourceInfo',
        'securityId',
        'majorVersion',
        'minorVersion'
    ]
    recordDict = {key: recordDict[key] for key in reorder}
    return recordDict


def findFirstRecord(infile):
    """
    Returns a pointer to the first USN record found
    Modified version of Dave Lassalle's 'parseusn.py'
    https://github.com/sans-dfir/sift-files/blob/master/scripts/parseusn.py
    """
    while True:
        data = infile.read(65536).lstrip(b'\x00')
        if data:
            return infile.tell() - len(data)


def findNextRecord(infile, journalSize):
    """
    There are runs of null bytes between USN records. I'm guessing
    this is done to ensure that journal records are cluster-aligned on disk.
    This function reads through these null bytes, returning an offset
    to the first byte of the the next USN record.
    """
    while True:
        try:
            recordLength = struct.unpack_from('<I', infile.read(4))[0]
            if recordLength:
                infile.seek(-4, 1)
                return infile.tell() + recordLength
        except struct.error:
            if infile.tell() >= journalSize:
                sys.exit()


def filetimeToHumanReadable(filetime):
    """
    Borrowed from Willi Ballenthin's parse_usnjrnl.py
    """
    try:
        return str(datetime.utcfromtimestamp(float(filetime) * 1e-7 - 11644473600))
    except ValueError:
        pass


def filetimeToEpoch(filetime):
    """
    Converts to Epoch Timestamp with milliseconds
    """
    return int(filetime / 10000 - 11644473600000)


def convertFileReference(buf):
    """
    Read, store, unpack, and return FileReference
    """
    b = memoryview(bytearray(struct.pack("<Q", buf)))
    seq = struct.unpack_from("<h", b[6:8])[0]

    b = memoryview(bytearray(b[0:6]))
    byteString = ''

    for i in b[::-1]:
        byteString += format(i, 'x')
    entry = int(byteString, 16)

    return seq, entry


def filenameHandler(infile, recordDict):
    """
    Read and return filename
    """
    try:
        filename = struct.unpack_from('<{}s'.format(
            recordDict['filenameLength']), infile.read(recordDict['filenameLength']))[0]
        return filename.decode('utf16')
    except struct.error:
        return ''


def convertAttributes(attributeType, data):
    """
    Identify attributes and return list
    """
    attributeList = [attributeType[i] for i in attributeType if i & data]
    return ' '.join(attributeList)


def main():
    """
    Main function for argument parsing and function execution
    """
    p = ArgumentParser(description=f'usnparser v{str(__version__)}')
    p.add_argument('-f', '--file',
                   metavar='FILE',
                   help='Parse the given USN journal file',
                   required=True)
    p.add_argument('-o', '--outfile',
                   metavar='FILE',
                   help='Output records to given file',
                   required=True)
    p.add_argument('-b', '--body',
                   help='Return USN records in body file format',
                   action='store_true')
    p.add_argument('-c', '--csv',
                   help='Return USN records in comma-separated format',
                   action='store_true')
    p.add_argument('-t', '--tln',
                   help='Return USN records in TLN format (use with -s to add hostname)',
                   action='store_true')
    p.add_argument('-s', '--system', metavar='NAME',
                   help='System hostname (use with -t)')
    p.add_argument('-V', '--verbose',
                   help='Return all USN properties for each record (JSON only)',
                   action='store_true')
    p.add_argument('-v', '--version', action='version', version=p.description)
    args = p.parse_args()

    journalSize = os.path.getsize(args.file)
    with open(args.file, 'rb') as i:
        with open(args.outfile, 'wb') as o:
            i.seek(findFirstRecord(i))

            if args.csv:
                o.write(b'timestamp,filename,fileattr,reason\n')
                while True:
                    nextRecord = findNextRecord(i, journalSize)
                    recordLength = struct.unpack_from('<I', i.read(4))[0]
                    recordData = struct.unpack_from('<2H4Q4I2H', i.read(56))
                    u = parseUsn(i, recordData)
                    u = '{0},{1},{2},{3}\n'.format(
                        u['humanTimestamp'],
                        u['filename'],
                        u['fileAttributes'],
                        u['reason'])
                    o.write(u.encode('utf8', errors='backslashreplace'))
                    i.seek(nextRecord)

            elif args.body:
                while True:
                    nextRecord = findNextRecord(i, journalSize)
                    recordLength = struct.unpack_from('<I', i.read(4))[0]
                    recordData = struct.unpack_from('<2H4Q4I2H', i.read(56))
                    u = parseUsn(i, recordData)
                    u = '0|{0} (USN: {1})|{2}-{3}|0|0|0|0|{4}|{4}|{4}|{4}\n'.format(
                        u['filename'],
                        u['reason'],
                        u['mftEntryNumber'],
                        u['mftSeqNumber'],
                        int(u['epochTimestamp'] / 1000),
                        int(u['epochTimestamp'] / 1000),
                        int(u['epochTimestamp'] / 1000),
                        int(u['epochTimestamp'] / 1000))
                    o.write(u.encode('utf8', errors='backslashreplace'))
                    i.seek(nextRecord)

            elif args.tln:
                if not args.system:
                    args.system = ''
                while True:
                    nextRecord = findNextRecord(i, journalSize)
                    recordLength = struct.unpack_from('<I', i.read(4))[0]
                    recordData = struct.unpack_from('<2H4Q4I2H', i.read(56))
                    u = parseUsn(i, recordData)
                    u = '{0}|USN|{1}||{2};{3}\n'.format(
                        u['epochTimestamp'],
                        args.system,
                        u['filename'],
                        u['reason'])
                    o.write(u.encode('utf8', errors='backslashreplace'))
                    i.seek(nextRecord)

            elif args.verbose:
                while True:
                    nextRecord = findNextRecord(i, journalSize)
                    recordLength = struct.unpack_from('<I', i.read(4))[0]
                    recordData = struct.unpack_from('<2H4Q4I2H', i.read(56))
                    u = json.dumps(parseUsn(i, recordData),
                                   indent=4, ensure_ascii=False)
                    o.write(u.encode('utf8', errors='backslashreplace'))
                    o.write(b'\n')
                    i.seek(nextRecord)

            else:
                while True:
                    nextRecord = findNextRecord(i, journalSize)
                    recordLength = struct.unpack_from('<I', i.read(4))[0]
                    recordData = struct.unpack_from('<2H4Q4I2H', i.read(56))
                    u = parseUsn(i, recordData)
                    u = '{0} | {1} | {2} | {3}\n'.format(
                        u['humanTimestamp'],
                        u['filename'],
                        u['fileAttributes'],
                        u['reason'])
                    o.write(u.encode('utf8', errors='backslashreplace'))
                    i.seek(nextRecord)


if __name__ == '__main__':
    main()
