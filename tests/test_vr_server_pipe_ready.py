from tools.vr_capture.launch_compositor import server_pipe_ready


def test_process_presence_and_namespace_do_not_prove_server_ready():
    namespace = 'Num RefCount Protocol Flags Type St Inode Path\n0: 2 0 10000 1 01 22 @/steamvr/SteamVR_Namespace\n'
    assert not server_pipe_ready([123], namespace)
    ready = namespace + '0: 2 0 10000 1 01 23 @/steamvr/VR_ServerPipe_123\n'
    assert server_pipe_ready([123], ready)
    assert not server_pipe_ready([12], ready)
    assert not server_pipe_ready([], ready)
