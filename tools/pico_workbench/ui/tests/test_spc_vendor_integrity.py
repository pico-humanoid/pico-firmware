"""Offline integrity check for the pinned vendor dependency, not a network test."""
import hashlib
import json
from pathlib import Path
import unittest
import platform_tools as tools

class SpcVendorIntegrityTests(unittest.TestCase):
    def test_pinned_official_source_files_are_exact_git_blobs(self):
        base=tools.project_dir('RS10P-Speed-CAN1')/'App/vendor/robstride_spc'
        meta=json.loads((base/'SOURCE.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['repository'],'https://github.com/RobStride/RobStrideSPC')
        self.assertEqual(meta['commit'],'d8451a447d7265becf71271a008a71f7063b7ecc')
        self.assertEqual(len(meta['upstream_files']),4)
        for name,record in meta['upstream_files'].items():
            raw=(base/'upstream'/name).read_bytes()
            actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            self.assertEqual(actual,record['git_blob_sha1'],name)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),record['sha256'],name)

if __name__=='__main__':unittest.main()
