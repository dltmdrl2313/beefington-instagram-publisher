import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import publisher


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.override = patch.object(publisher, 'ROOT', self.root)
        self.override.start()
        self.now = datetime(2026, 10, 19, 9, 15, tzinfo=publisher.KST)
        data = b'\xff\xd8\xfftest-jpeg'
        (self.root / 'meme.jpg').write_bytes(data)
        self.item = dict(id='2026-10-19-09', scheduled_at='2026-10-19T09:00:00+09:00',
                         approved=True, image='meme.jpg', caption='A prepared caption. #AIGenerated',
                         sha256=hashlib.sha256(data).hexdigest(),
                         sources=[dict(url='https://example.com/trend', observed_at='2026-10-18T10:00:00+09:00')])

    def tearDown(self):
        self.override.stop()
        self.temp.cleanup()

    def test_due_and_not_yet_due(self):
        self.assertEqual(publisher.choose([self.item], {}, self.now), self.item)
        self.assertIsNone(publisher.choose([self.item], {}, self.now - timedelta(hours=1)))

    def test_no_catch_up(self):
        self.assertIsNone(publisher.choose([self.item], {}, self.now + timedelta(hours=2)))

    def test_no_repeat_after_ambiguous_or_successful_submission(self):
        for state in ('creating', 'publishing', 'uncertain', 'published'):
            self.assertIsNone(publisher.choose([self.item], {self.item['id']: {'status': state}}, self.now))

    def test_unapproved_is_not_published(self):
        self.item['approved'] = False
        self.assertIsNone(publisher.choose([self.item], {}, self.now))

    def test_reject_old_trend(self):
        self.item['sources'][0]['observed_at'] = '2026-09-01T10:00:00+09:00'
        with self.assertRaises(ValueError):
            publisher.choose([self.item], {}, self.now)

    def test_reject_tampered_image(self):
        (self.root / 'meme.jpg').write_bytes(b'\xff\xd8\xffchanged')
        with self.assertRaises(ValueError):
            publisher.choose([self.item], {}, self.now)

    def test_duplicate_slot(self):
        with self.assertRaises(ValueError):
            publisher.choose([self.item, dict(self.item, id='second')], {}, self.now)

    def test_other_timezone_same_instant(self):
        self.item['scheduled_at'] = '2026-10-19T00:00:00+00:00'
        self.assertIsNotNone(publisher.choose([self.item], {}, self.now))

    def test_outside_repository_is_rejected(self):
        self.item['image'] = '../outside.jpg'
        with self.assertRaises(ValueError):
            publisher.choose([self.item], {}, self.now)


if __name__ == '__main__':
    unittest.main()
