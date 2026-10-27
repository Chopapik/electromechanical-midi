"""WebSocket Play -> real pipeline -> TCP gateway -> BLE adapter -> C++ parser.

Only radio delivery and electrical IO are simulated. No physical BLE discovery,
ATX switching, flashing or instrument motion takes place in this suite.
"""
import asyncio
import functools
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import mido
from fastapi.testclient import TestClient
from ble_configuration import validate_configuration
from ble_gateway import serve_client
from ble_link import BleBytes, BleOrchestraLink, GatewayBytes, ACK, TX
from runtime.application import Application
from web.server import create_app
from test_ble_execution_ack import AckClient, Scanner
from test_esp32_protocol import SOURCE, ROOT


CPP = SOURCE.split('int main(')[0] + r'''
#include <iostream>
#include <chrono>
int main(){
 Fake io;Controller ctrl(io);ctrl.begin();Sink sink;Led led;
 CommandProtocol p(ctrl,sink,led);p.newBleSession(1);
 // Simulated supply and TRACK0 only. This executable has no physical IO.
 ctrl.command("POWER ON");for(auto& active:io.active)active=true;
 auto started=std::chrono::steady_clock::now();
 std::cout<<"READY\n"<<std::flush;
 std::string hex;
 while(std::getline(std::cin,hex)){
  sink.replies.clear();
  // Motor pulse/cooldown time must advance with the delayed radio clock.
  // Advancing a fixed 10ms per packet falsely leaves HDD bridges BUSY.
  auto elapsed=std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::steady_clock::now()-started).count();
  uint32_t target=10000+uint32_t(elapsed);
  while(int32_t(target-io.now)>0){io.now+=100;ctrl.tick();p.pollErrors();}
  for(size_t i=0;i<hex.size();i+=2)
   p.input(Transport::Ble,uint8_t(std::stoul(hex.substr(i,2),nullptr,16)));
  ctrl.tick();p.pollErrors();
  for(auto& r:sink.replies)std::cout<<r.text<<"\n";
  std::cout<<".\n"<<std::flush;
 }
}
'''


class GatewayServer:
    def __enter__(self):
        self.ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.sessions = set()
        async def start():
            async def session(reader, writer):
                task = asyncio.current_task()
                self.sessions.add(task)
                try:
                    await serve_client(reader, writer)
                finally:
                    self.sessions.discard(task)
            self.server = await asyncio.start_server(session, '127.0.0.1', 0)
            self.address = '127.0.0.1:' + str(self.server.sockets[0].getsockname()[1])
            self.ready.set()
        def work():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(start())
            self.loop.run_forever()
            self.loop.close()
        self.thread = threading.Thread(target=work)
        self.thread.start()
        assert self.ready.wait(5)
        return self

    def __exit__(self, *_):
        async def stop():
            self.server.close()
            await self.server.wait_closed()
            for task in list(self.sessions):
                task.cancel()
            await asyncio.gather(*self.sessions, return_exceptions=True)
        asyncio.run_coroutine_threadsafe(stop(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


class PlaybackE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        source = Path(cls.directory.name) / 'controller.cpp'
        source.write_text(CPP)
        cls.binary = source.with_suffix('')
        compiler = shutil.which('clang++') or shutil.which('g++')
        subprocess.run([compiler, '-std=c++11', '-I', str(ROOT/'firmware/controller/include'),
                        str(source), '-o', str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_song(self, path, *, legacy_configuration=False, play_seconds=1, position=0,
                 preplan=False, ack_delay=.095):
        clients = []
        binary = self.binary
        class CppClient(AckClient):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE,
                                                stdout=subprocess.PIPE, text=True)
                if self.process.stdout.readline() != 'READY\n':
                    raise RuntimeError('Simulated firmware did not boot')
                self.commands = []
                self.errors = []
                self.ack_delay = 0
                clients.append(self)

            async def __aexit__(self, *_):
                self.process.stdin.close()
                self.process.wait(3)
                self.process.stdout.close()

            async def write_gatt_char(self, uuid, data, response):
                self.sent.append(data)
                self.line += data
                while b'\n' in self.line:
                    line, _, self.line = self.line.partition(b'\n')
                    self.commands.append(line.decode())
                self.process.stdin.write(data.hex()+'\n')
                self.process.stdin.flush()
                while True:
                    line = self.process.stdout.readline()
                    if line == '.\n':
                        break
                    if not line:
                        raise RuntimeError('C++ controller stopped unexpectedly')
                    if line.startswith('ERR'):
                        self.errors.append(line.strip())
                    channel = ACK if line.startswith('SYNCED ') else TX
                    if channel == ACK:
                        asyncio.get_running_loop().call_later(
                            self.ack_delay, self.callbacks[channel], None, line.encode())
                    else:
                        for offset in range(0, len(line), 20):
                            self.callbacks[channel](None, line[offset:offset+20].encode())

        class LegacyCapacity(BleBytes):
            @property
            def command_capacity(self):
                return max(96, self.write_size-16)
        transport = LegacyCapacity if legacy_configuration else BleBytes
        factory = functools.partial(transport, scanner=Scanner(), client_factory=CppClient)
        with patch('ble_gateway.BleBytes', factory), GatewayServer() as server:
            def connect():
                link = BleOrchestraLink(GatewayBytes(server.address))
                if legacy_configuration:
                    # Reproduce the previous application, not an alternative
                    # production path: setup was an unpaced musical burst.
                    link.send_configuration = link.send_batch
                return link
            runtime = Application(connect=connect)
            if preplan:
                # The real gateway is a separate native process. For large
                # local corpora, avoid sharing the planner's GIL with this
                # in-process simulated gateway. CI also covers WS file load.
                runtime.load(path)
            self.assertTrue(runtime.service.connect(), runtime.service.error)
            # The regression concerns Play, after a successful handshake.
            clients[0].ack_delay = ack_delay
            app = create_app(midi_dir=path.parent, runtime=runtime, connect_on_start=False)
            with TestClient(app) as http, http.websocket_connect('/ws') as ws:
                def command(action, **fields):
                    token = str(time.monotonic_ns())
                    ws.send_json({'action':action, 'requestId':token, **fields})
                    while True:
                        message = ws.receive_json()
                        if message.get('requestId') == token:
                            return message
                if not preplan:
                    self.assertEqual(command('set_file', file=path.name)['type'], 'ack')
                if position:
                    self.assertEqual(command('seek', position=position)['type'], 'ack')
                if legacy_configuration:
                    with self.assertLogs('orchestra.ble', level='WARNING'):
                        result = command('play')
                    self.assertEqual(result['type'], 'error')
                    self.assertIn('realtime overrun', result['message'])
                    self.assertFalse(any(' PLAY ' in line for line in clients[0].commands))
                    return
                result = command('play')
                self.assertEqual(result['type'], 'ack', result)
                deadline = time.monotonic()+play_seconds+8
                while time.monotonic() < deadline:
                    state = http.get('/api/state').json()
                    self.assertIsNone(state['error'])
                    if state['state'] == 'playing' and state['position'] > position+play_seconds:
                        break
                    time.sleep(.02)
                else:
                    self.fail('Play did not progress past homing into the song')
                self.assertTrue(state['output']['connected'])
                self.assertFalse(state['output']['unknown'])
                self.assertTrue(any(' PLAY ' in line for line in clients[0].commands))
                self.assertFalse(clients[0].errors, clients[0].errors)
                self.assertEqual(command('pause')['type'], 'ack')
                self.assertEqual(command('seek', position=.5)['type'], 'ack')
                self.assertEqual(command('play')['type'], 'ack')
                self.assertEqual(command('stop')['type'], 'ack')
                stopped = http.get('/api/state').json()
                self.assertEqual(stopped['state'], 'stopped')
                self.assertFalse(stopped['output']['unknown'])
                self.assertTrue(clients[0].commands[-2].startswith('ALL STOP '))
                return {'file':path.name, 'position':position, 'playedSeconds':state['position']-position,
                        'commands':len(clients[0].commands), 'timing':state['timing'],
                        'stopConfirmed':True, 'simulatedAckDelayMs':ack_delay*1000,
                        'plannedBeforeTransport':preplan}

    def song(self):
        path = Path(self.directory.name)/'dense.mid'
        midi = mido.MidiFile()
        # Real parser, classifier, allocation and compiler, including simultaneous
        # voices and repeated phrases; no hand-crafted ExecutionTimeline.
        for channel in range(6):
            track = mido.MidiTrack()
            track.append(mido.Message('program_change', channel=channel, program=channel*8))
            for note in [60, 64, 67, 62, 65, 69]*3:
                track.append(mido.Message('note_on', channel=channel, note=note+channel, velocity=100))
                track.append(mido.Message('note_off', channel=channel, note=note+channel, time=240))
            midi.tracks.append(track)
        midi.save(path)
        return path

    def test_old_startup_fails_before_music_with_realistic_ack_delays(self):
        self.run_song(self.song(), legacy_configuration=True)

    def test_play_configures_homes_plays_pauses_seeks_and_confirms_stop(self):
        self.run_song(self.song())

    def test_configuration_rejects_motion_power_and_injection(self):
        for line in ('FDD 1 PLAY 220', 'FDD 1 HOME', 'HDD 1 HIT',
                     'POWER ON', 'VHS AMP 50', 'VHS FREQ 440',
                     'FDD 1 ENABLE 1\r', 'FDD 1 ENABLE 1\nPOWER ON'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                validate_configuration((line+'\n').encode())
