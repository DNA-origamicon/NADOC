"""Exercise Python-to-native framing, exact bytes, backpressure and rejection."""
import socket
import struct
import subprocess
from pathlib import Path
import pytest
from backend.api.vr_view_transport import address, send_snapshot


@pytest.fixture(scope='module')
def receiver(tmp_path_factory):
    directory = tmp_path_factory.mktemp('inbox')
    source = directory/'receiver.cpp'
    source.write_text('''
#include "view_snapshot_inbox.hpp"
#include <iostream>
int main(int argc,char** argv){
 nadoc_vr::ViewSnapshotInbox inbox(argv[1],argc<5);
 std::cout<<"ready\\n"<<std::flush;
 if(argc>3)std::this_thread::sleep_for(std::chrono::milliseconds(100));
 for(int i=0;i<std::stoi(argv[2]);++i){
  const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(5);
  while(std::chrono::steady_clock::now()<end){
   if(auto packet=inbox.take()){std::cout.write(packet->data(),packet->size());std::cout.flush();break;}
   std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
 }
}
''')
    binary = directory/'receiver'
    subprocess.run(['g++','-std=c++20','-pthread','-I',str(Path('native/vr_viewer/src').resolve()),str(source),'-o',str(binary)],check=True)
    return binary


def packet(version, tail=b''):
    return b'NADOCVT1'+struct.pack('<10I',6,version,2048,0,0,0,0,0,0,0)+tail


def test_native_receives_exact_packets_and_rejects_partial_and_oversized(receiver,tmp_path):
    path=str(tmp_path/'event')
    process=subprocess.Popen([str(receiver),path,'2'],stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline()==b'ready\n'
        for size,body in [(256*1024*1024+1,b''),(100,b'partial'),(48,b'x'*48)]:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(address(path));client.sendall(struct.pack('<I',size)+body)
        for version,tail in [(1,bytes(range(256))*8192),(2,b'exact final bytes')]:
            data=packet(version,tail)
            assert send_snapshot(path,data)
            assert process.stdout.read(len(data))==data
        assert process.wait(timeout=5)==0
    finally:
        if process.poll() is None:process.kill()
        process.wait()


def test_missing_listener_uses_legacy_fallback(tmp_path):
    assert send_snapshot(str(tmp_path/'absent'),packet(1)) is False


def test_transport_rejects_invalid_size(tmp_path):
    with pytest.raises(ValueError):send_snapshot(str(tmp_path/'event'),b'bad')


def test_pending_packet_is_not_overwritten_before_native_takes_it(receiver,tmp_path):
    path=str(tmp_path/'backpressure')
    process=subprocess.Popen([str(receiver),path,'2','delay'],stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline()==b'ready\n'
        first,second=packet(1),packet(2)
        assert send_snapshot(path,first)
        assert send_snapshot(path,second)
        assert process.stdout.read(len(first)+len(second))==first+second
        assert process.wait(timeout=5)==0
    finally:
        if process.poll() is None:process.kill()
        process.wait()


def test_control_channel_preserves_text_bytes(receiver,tmp_path):
    path=str(tmp_path/'event.simulations')
    process=subprocess.Popen([str(receiver),path,'1','delay','control'],stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline()==b'ready\n'
        data='unchanged control format: μ 1 0'.encode()
        assert send_snapshot(path,data,display=False)
        assert process.stdout.read(len(data))==data
        assert process.wait(timeout=5)==0
    finally:
        if process.poll() is None:process.kill()
        process.wait()


def test_native_negotiates_transform_support_without_changing_packet_bytes(receiver,tmp_path):
    path=str(tmp_path/'capabilities')
    process=subprocess.Popen([str(receiver),path,'1'],stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline()==b'ready\n'
        data=packet(1);capabilities={}
        assert send_snapshot(path,data,capabilities=capabilities)
        assert capabilities=={'transform_updates':True}
        assert process.stdout.read(len(data))==data
        assert process.wait(timeout=5)==0
    finally:
        if process.poll() is None:process.kill()
        process.wait()


def test_older_listener_remains_supported_without_transform_capability(tmp_path):
    import threading
    path=str(tmp_path/'old-viewer')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
        server.bind(address(path));server.listen(1)
        def receive():
            client,_=server.accept()
            with client:
                size=struct.unpack('<I',client.recv(4))[0]
                data=b''
                while len(data)<size:data+=client.recv(size-len(data))
                client.sendall(b'\x01')
        worker=threading.Thread(target=receive);worker.start()
        try:
            capabilities={}
            assert send_snapshot(path,packet(1),capabilities=capabilities)
            assert capabilities=={'transform_updates':False}
        finally:worker.join(timeout=5)
        assert not worker.is_alive()
