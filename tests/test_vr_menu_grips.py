"""The grip pixel oracle requires a visible frame in the expected state."""
from PIL import Image, ImageDraw
from tools.vr_workflows.menu_grip_check import frame_pixels


def test_grip_frame_pixels_reject_blank_wrong_state_and_offscreen(tmp_path):
    eye = {'eye': 'left', 'position': [0, 0, 0], 'orientation_xyzw': [0, 0, 0, 1],
           'width': 200, 'height': 200, 'fov_left_right_up_down': [-.785398, .785398, .785398, -.785398]}
    menu = {'grip_state': 'resizing', 'grip_targets': [[-.5, 0, -1], [.5, 0, -1], [0, .5, -1], [0, -.5, -1]]}
    evidence = {'eyes': [eye], 'state': {'sidebars': [menu]}}
    image = Image.new('RGB', (200, 200))
    image.save(tmp_path/'left.png')
    assert not frame_pixels(tmp_path, evidence, 0, 'resizing')[0]['passed']
    ImageDraw.Draw(image).rectangle((50, 50, 150, 150), outline=(100, 220, 150), width=3)
    image.save(tmp_path/'left.png')
    assert frame_pixels(tmp_path, evidence, 0, 'resizing')[0]['passed']
    menu['grip_state'] = 'moving'
    assert not frame_pixels(tmp_path, evidence, 0, 'moving')[0]['passed']
    menu['grip_state'] = 'resizing'
    menu['grip_targets'] = [[x+10, y, z] for x, y, z in menu['grip_targets']]
    assert not frame_pixels(tmp_path, evidence, 0, 'resizing')[0]['passed']
