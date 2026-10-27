import hashlib
import io
import unittest
import zipfile
from updater import FILES, unpack, version


class UpdaterTests(unittest.TestCase):
    def package(self, extra=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for name in FILES:
                z.writestr(name, '3.1.0' if name == 'VERSION' else '')
            if extra:
                z.writestr(extra, 'unexpected')
        data = buf.getvalue()
        return data, 'sha256:' + hashlib.sha256(data).hexdigest()

    def test_verified_complete_package(self):
        self.assertEqual(set(unpack(*self.package())), FILES)

    def test_reject_corruption(self):
        data, digest = self.package()
        with self.assertRaises(ValueError):
            unpack(data + b'corrupt', digest)

    def test_reject_traversal(self):
        with self.assertRaises(ValueError):
            unpack(*self.package('../overlay.py'))

    def test_version_order(self):
        self.assertGreater(version('v3.10.0'), version('3.9.0'))
        with self.assertRaises(ValueError):
            version('latest')
