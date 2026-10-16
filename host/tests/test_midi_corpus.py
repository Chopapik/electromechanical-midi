"""Corpus identity and holdout isolation, including alternate MIDI versions."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

from test_allocator import write_tracks
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from build_midi_corpus import build


class CorpusTests(unittest.TestCase):
    def test_duplicates_do_not_vote_twice_and_prior_examples_never_enter_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            p=write_tracks(root/'0001-01-radiohead_1993-you.mid',[('Piano',0,[(0,1,60)])])
            (root/'copy.mid').write_bytes(p.read_bytes())
            sha=hashlib.sha256(p.read_bytes()).hexdigest()
            a=build([root],[sha]);b=build([root],[sha])
            self.assertEqual(a,b)
            self.assertEqual((a['files'],a['unique']),(2,1))
            self.assertEqual(a['songs'][0]['split'],'development')
            self.assertEqual(len(a['songs'][0]['aliases']),2)

    def test_versions_and_transitive_metadata_aliases_share_one_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            a=write_tracks(root/'0001-01-radiohead_1993-you.mid',[('A',0,[(0,1,60)])])
            # Same notes, unrelated import name and distinct metadata bytes.
            write_tracks(root/'alternate.mid',[('B',0,[(0,1,60)])])
            write_tracks(root/'alternate (live).mid',[('C',0,[(0,1,62)])])
            write_tracks(root/'Radiohead - You (acoustic).mid',[('D',0,[(0,1,64)])])
            report=build([root],[hashlib.sha256(a.read_bytes()).hexdigest()])
            self.assertEqual(report['unique'],4)
            self.assertEqual(len({r['group'] for r in report['songs']}),1)
            self.assertEqual({r['split'] for r in report['songs']},{'development'})

    def test_bad_midi_is_reported_and_missing_root_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'broken.mid').write_bytes(b'not MIDI')
            report=build([root])
            self.assertEqual(report['unique'],0);self.assertEqual(len(report['errors']),1)
            with self.assertRaises(FileNotFoundError):build([root/'missing'])


if __name__=='__main__':unittest.main()
