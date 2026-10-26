"""One MIDI importer and transport error mapping; temporary files, no hardware."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'host'))
from fastapi.testclient import TestClient
from midi_source import MidiSource
from web.library import MidiLibrary, MidiLibraryError, MAX_UPLOAD_BYTES
from web.server import create_app


class MidiLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'midi'
        self.library=MidiLibrary(self.directory)
        self.data=(ROOT/'midi/test.mid').read_bytes()

    def assert_error(self,code,operation):
        with self.assertRaises(MidiLibraryError) as caught:
            operation()
        self.assertEqual(caught.exception.code,code)
        return caught.exception

    def test_save_upload_is_the_single_validated_import_operation(self):
        path=self.library.save_upload('song.MIDI',self.data)
        self.assertEqual(path,self.directory/'song.MIDI')
        self.assertEqual(path.read_bytes(),self.data)
        self.assertEqual(self.library.resolve(path.name),path.resolve())
        self.assertGreater(MidiSource(path).duration,0)
        self.assertEqual(self.library.list_files()[0]['name'],'song.MIDI')
        self.assertEqual(self.library.metadata(path.name)['name'],'song.MIDI')
        self.assertEqual(list(self.directory.iterdir()),[path])

    def test_corrupt_and_empty_midi_leave_no_working_file(self):
        for data in (b'',b'not MIDI',b'MThd\x00'):
            with self.subTest(data=data):
                self.assert_error('invalid_midi',lambda:self.library.save_upload('bad.mid',data))
                self.assertEqual(list(self.directory.iterdir()),[])

    def test_wrong_extensions_and_hidden_names_do_not_create_directory(self):
        for name in ('','.hidden.mid','song.wav','song'):
            with self.subTest(name=name):
                self.assert_error('invalid_upload_name',lambda:self.library.save_upload(name,self.data))
                self.assertFalse(self.directory.exists())

    def test_limit_matches_current_endpoint_and_is_checked_before_disk(self):
        self.assertEqual(MAX_UPLOAD_BYTES,5*1024*1024)
        self.assert_error('upload_too_large',
                          lambda:self.library.save_upload('large.mid',b'x'*(MAX_UPLOAD_BYTES+1)))
        self.assertFalse(self.directory.exists())
        # Exactly at the boundary reaches content validation, not size rejection.
        self.assert_error('invalid_midi',
                          lambda:self.library.save_upload('large.mid',b'x'*MAX_UPLOAD_BYTES))
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_collision_uses_existing_endpoint_dash_names_and_never_overwrites(self):
        names=[self.library.save_upload('song.midi',self.data).name for _ in range(3)]
        self.assertEqual(names,['song.midi','song-1.mid','song-2.mid'])
        self.assertTrue(all(path.read_bytes()==self.data for path in self.directory.iterdir()))

    def test_upload_strips_posix_directory_and_preserves_current_whitespace(self):
        path=self.library.save_upload('../../song.mid',self.data)
        self.assertEqual(path,self.directory/'song.mid')
        self.assertFalse((Path(self.temp.name)/'song.mid').exists())
        path=self.library.save_upload(' spaced.mid',self.data)
        self.assertEqual(path.name,' spaced.mid')

    def test_resolve_rejects_paths_and_symlinks_outside_library(self):
        self.directory.mkdir()
        for name in ('','../song.mid','./song.mid','.hidden.mid','sub/song.mid','sub\\song.mid'):
            with self.subTest(name=name):
                self.assert_error('invalid_name',lambda:self.library.resolve(name))
        outside=Path(self.temp.name)/'outside.mid';outside.write_bytes(self.data)
        (self.directory/'linked.mid').symlink_to(outside)
        self.assert_error('outside_library',lambda:self.library.resolve('linked.mid'))
        self.assert_error('not_found',lambda:self.library.resolve('missing.mid'))

    def test_upload_dangling_symlink_cannot_write_outside_library(self):
        self.directory.mkdir()
        outside=Path(self.temp.name)/'outside.mid'
        (self.directory/'song.mid').symlink_to(outside)
        path=self.library.save_upload('song.mid',self.data)
        self.assertEqual(path.name,'song-1.mid')
        self.assertFalse(outside.exists())
        self.assertTrue((self.directory/'song.mid').is_symlink())

    def test_exclusive_write_handles_a_name_claimed_after_validation(self):
        real_open=Path.open
        claimed=False
        def claim_name(path,*args,**kwargs):
            nonlocal claimed
            if path.name=='song.mid' and args==('xb',) and not claimed:
                claimed=True
                with real_open(path,'wb') as stream:stream.write(b'already claimed')
            return real_open(path,*args,**kwargs)
        with patch.object(Path,'open',new=claim_name):
            path=self.library.save_upload('song.mid',self.data)
        self.assertEqual(path.name,'song-1.mid')
        self.assertEqual((self.directory/'song.mid').read_bytes(),b'already claimed')

    def test_validation_and_final_write_failures_clean_working_files(self):
        with patch('web.library.MidiSource',side_effect=RuntimeError('parser failed')):
            self.assert_error('invalid_midi',lambda:self.library.save_upload('song.mid',self.data))
        self.assertEqual(list(self.directory.iterdir()),[])
        with patch.object(Path,'open',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):
                self.library.save_upload('song.mid',self.data)
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_directory_creation_error_remains_an_io_error(self):
        with patch.object(Path,'mkdir',side_effect=PermissionError('read only')):
            with self.assertRaisesRegex(PermissionError,'read only'):
                self.library.save_upload('song.mid',self.data)

    def test_partial_final_write_is_removed_without_touching_existing_file(self):
        self.library.save_upload('song.mid',self.data)
        real_open=Path.open
        class FailingWrite:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*_):self.stream.close()
            def write(self,data):
                self.stream.write(data[:8])
                raise OSError('disk full after partial write')
        def broken_open(path,*args,**kwargs):
            stream=real_open(path,*args,**kwargs)
            return FailingWrite(stream) if args==('xb',) else stream
        with patch.object(Path,'open',new=broken_open):
            with self.assertRaisesRegex(OSError,'disk full after partial write'):
                self.library.save_upload('song.mid',self.data)
        self.assertEqual([p.name for p in self.directory.iterdir()],['song.mid'])
        self.assertEqual((self.directory/'song.mid').read_bytes(),self.data)

    def test_metadata_parser_failure_is_a_domain_error(self):
        self.directory.mkdir()
        (self.directory/'bad.mid').write_bytes(b'not MIDI')
        self.assert_error('invalid_midi',lambda:self.library.metadata('bad.mid'))


class MidiLibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'midi'
        self.data=(ROOT/'midi/test.mid').read_bytes()
        self.client=TestClient(create_app(midi_dir=self.directory,connect_on_start=False),
                               raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def upload(self,name,data=None):
        return self.client.post('/api/files',files={'file':(name,self.data if data is None else data,'audio/midi')})

    def test_upload_response_collision_and_metadata_preserve_wire_contract(self):
        first=self.upload('song.midi');second=self.upload('song.midi')
        self.assertEqual((first.status_code,first.json()),(200,{'name':'song.midi'}))
        self.assertEqual((second.status_code,second.json()),(200,{'name':'song-1.mid'}))
        meta=self.client.get('/api/files/song.midi')
        self.assertEqual(meta.status_code,200)
        self.assertEqual(meta.json()['name'],'song.midi')
        self.assertEqual({f['name'] for f in self.client.get('/api/files').json()},
                         {'song.midi','song-1.mid'})

    def test_import_error_statuses_and_existing_messages(self):
        for name,data,status,detail in (
                ('bad.wav',b'x',422,'Wybierz plik MIDI'),
                ('.hidden.mid',b'x',422,'Wybierz plik MIDI'),
                ('large.mid',b'x'*(MAX_UPLOAD_BYTES+1),413,'MIDI przekracza 5 MB')):
            with self.subTest(name=name):
                result=self.upload(name,data)
                self.assertEqual((result.status_code,result.json()),(status,{'detail':detail}))
        for data in (b'',b'not MIDI'):
            result=self.upload('bad.mid',data)
            self.assertEqual(result.status_code,422)
            self.assertIn('nie moge wczytac',result.json()['detail'])
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_resolve_and_metadata_errors_are_mapped_to_existing_http_statuses(self):
        self.assertEqual(self.client.get('/api/files/.hidden.mid').status_code,400)
        missing=self.client.get('/api/files/missing.mid')
        self.assertEqual((missing.status_code,missing.json()),
                         (404,{'detail':'nie ma pliku missing.mid'}))
        self.directory.mkdir()
        (self.directory/'bad.mid').write_bytes(b'not MIDI')
        self.assertEqual(self.client.get('/api/files/bad.mid').status_code,422)

    def test_endpoint_delegates_to_library_import_operation(self):
        target=self.directory/'chosen.mid'
        with patch.object(MidiLibrary,'save_upload',return_value=target) as save:
            result=self.upload('song.mid')
        save.assert_called_once_with('song.mid',self.data)
        self.assertEqual(result.json(),{'name':'chosen.mid'})

    def test_set_file_preserves_existing_websocket_error_text(self):
        # A domain exception must still pass through the controller's mapper.
        with TestClient(create_app(midi_dir=self.directory,connect_on_start=False)) as client:
            with client.websocket_connect('/ws') as peer:
                peer.receive_json()
                peer.send_json({'action':'set_file','file':'missing.mid','requestId':'missing'})
                while True:
                    result=peer.receive_json()
                    if result.get('requestId')=='missing':break
                self.assertEqual(result,{'type':'error','requestId':'missing',
                                         'message':'404: nie ma pliku missing.mid'})

    def test_write_error_does_not_become_success_and_leaves_no_working_file(self):
        with patch.object(Path,'open',side_effect=OSError('disk full')):
            result=self.upload('song.mid')
        self.assertEqual(result.status_code,500)
        self.assertEqual(list(self.directory.iterdir()),[])
