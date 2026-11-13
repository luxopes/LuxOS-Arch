"""Native model/export tests. Builds and artifacts stay on disk under out/.

No user display, session bus, keyring or real user configuration is used. The
compiled driver only performs model operations and headless image rendering.
"""
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib

PACKAGE = Path(__file__).resolve().parents[1]
REPO = next((p for p in PACKAGE.parents if (p / "packages/apps").is_dir()), PACKAGE)
NS = {'s': 'http://www.w3.org/2000/svg'}


def png_bytes(width=2, height=2):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    pixels = b''.join(b'\x00' + bytes([230, 70, 110, 255]) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def rgba_rows(path):
    """Decode the encoder's 8-bit RGBA PNG without a Python imaging dependency."""
    data = path.read_bytes()
    width, height = struct.unpack('>II', data[16:24])
    assert data[24:26] == bytes([8, 6]), 'expected 8-bit RGBA PNG'
    compressed, offset = bytearray(), 8
    while offset < len(data):
        length = struct.unpack('>I', data[offset:offset+4])[0]
        if data[offset+4:offset+8] == b'IDAT':
            compressed.extend(data[offset+8:offset+8+length])
        offset += length + 12
    decoded = zlib.decompress(compressed)
    rows, previous, offset = [], bytearray(width * 4), 0
    for _ in range(height):
        method = decoded[offset]; offset += 1
        row = bytearray(decoded[offset:offset + width*4]); offset += width*4
        for index in range(len(row)):
            left = row[index-4] if index >= 4 else 0
            above = previous[index]
            diagonal = previous[index-4] if index >= 4 else 0
            if method == 1:
                predictor = left
            elif method == 2:
                predictor = above
            elif method == 3:
                predictor = (left + above) // 2
            elif method == 4:
                p = left + above - diagonal
                distances = [abs(p-left), abs(p-above), abs(p-diagonal)]
                predictor = [left, above, diagonal][distances.index(min(distances))]
            else:
                assert method == 0
                predictor = 0
            row[index] = (row[index] + predictor) & 255
        rows.append(row); previous = row
    return width, height, rows


@unittest.skipUnless(shutil.which('lsl'), 'LSL compiler is unavailable')
class IconEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artifacts = REPO / 'out'
        artifacts.mkdir(exist_ok=True)
        cls.build = tempfile.TemporaryDirectory(prefix='icon-engine-test-', dir=artifacts)
        cls.folder = Path(cls.build.name)
        for name in ('icon_model.lsl', 'icon_render.lsl', 'icon_cli.lsl'):
            shutil.copy2(PACKAGE / 'files' / name, cls.folder / name)
        shutil.copy2(PACKAGE / 'tests/test_driver.lsl', cls.folder / 'test_driver.lsl')
        cls.binary = cls.folder / 'driver'
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(cls.folder / 'test_driver.lsl'), str(cls.binary)],
                       check=True, capture_output=True, text=True, timeout=180)
        cls.env = dict(PATH='/usr/bin:/bin', HOME=str(cls.folder), LANG='C.UTF-8',
                       XDG_CONFIG_HOME=str(cls.folder / 'config'), XDG_DATA_HOME=str(cls.folder / 'data'),
                       XDG_CACHE_HOME=str(cls.folder / 'cache'), GSETTINGS_BACKEND='memory',
                       NO_AT_BRIDGE='1', GIO_USE_VFS='local', GTK_USE_PORTAL='0')

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def actions(self, *actions):
        path = self.folder / 'requests.json'
        path.write_text(json.dumps(actions, ensure_ascii=False))
        result = subprocess.run([str(self.binary), str(path)], env=self.env,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('CRITICAL', result.stderr)
        # CLI actions print a status line before the driver result.
        return json.loads(result.stdout.splitlines()[-1])

    def preset(self, name='aurora'):
        result = self.actions(dict(command='normalize', preset=name))[0]
        self.assertTrue(result['ok'], result)
        return result['value']

    def test_native_project_presets_and_distinct_designs(self):
        aurora, ember, blank = [self.preset(name) for name in ('aurora', 'ember', 'blank')]
        self.assertEqual(aurora['format'], 1)
        self.assertEqual(aurora['canvas'], 1024)
        self.assertEqual(len(aurora['layers']), 3)
        self.assertNotEqual(aurora['layers'][0]['color'], ember['layers'][0]['color'])
        self.assertEqual(blank['layers'], [])

    def test_duplicate_move_remove_preserve_independent_layers(self):
        value = self.actions(dict(command='mutate'))[0]
        self.assertTrue(value['ok'], value)
        layers = value['value']['layers']
        self.assertEqual(len(layers), 4)
        self.assertEqual(layers[0]['name'], 'Added copy')
        self.assertEqual(layers[0]['x'], 280)
        self.assertEqual(len(set(item['id'] for item in layers)), 4)
        self.assertEqual(layers[1]['x'], 100)

    def test_save_reopen_and_atomic_failure_preserves_existing_file(self):
        path = self.folder / 'saved.luxicon'
        original = self.preset()
        result = self.actions(dict(command='save', project=original, path=str(path)))[0]
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['value'], original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        before = path.read_bytes()
        invalid = copy.deepcopy(original)
        invalid['layers'][0]['color'] = 'url(http://example.test)'
        failed = self.actions(dict(command='save', project=invalid, path=str(path)))[0]
        self.assertFalse(failed['ok'])
        self.assertEqual(path.read_bytes(), before)
        missing = self.actions(dict(command='save', project=original,
                                    path=str(self.folder / 'missing-parent/icon.luxicon')))[0]
        self.assertFalse(missing['ok'])
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_formats_duplicate_ids_and_layer_limits(self):
        original = self.preset()
        examples = []
        for field, value in [('format', 2), ('canvas', 1000000), ('layers', 'invalid')]:
            project = copy.deepcopy(original); project[field] = value; examples.append(project)
        project = copy.deepcopy(original); project['layers'][1]['id'] = project['layers'][0]['id']; examples.append(project)
        project = copy.deepcopy(original); project['layers'] *= 22; examples.append(project)
        project = copy.deepcopy(original); project['layers'][0]['width'] = 'infinity'; examples.append(project)
        project = copy.deepcopy(original); project['layers'][0]['visible'] = 'true'; examples.append(project)
        project = copy.deepcopy(original); project['layers'][0]['kind'] = 'script'; examples.append(project)
        results = self.actions(*(dict(command='normalize', project=value) for value in examples))
        self.assertTrue(all(not result['ok'] for result in results), results)

    def test_geometry_is_bounded_and_svg_escapes_user_text(self):
        project = self.preset('blank')
        layer = self.preset()['layers'][0]
        layer.update(kind='text', text='A <b> & "B" </text><script>bad()</script>',
                     x=-999999, width=999999, opacity=99, rotation=9999)
        project['layers'] = [layer]
        project['title'] = '<evil>& title'
        clean, rendered = self.actions(dict(command='normalize', project=project), dict(command='svg', project=project))
        self.assertTrue(clean['ok'], clean)
        self.assertEqual(clean['value']['layers'][0]['width'], 4096)
        self.assertEqual(clean['value']['layers'][0]['x'], -4096)
        self.assertEqual(clean['value']['layers'][0]['opacity'], 1)
        self.assertTrue(rendered['ok'], rendered)
        tree = ET.fromstring(rendered['value'])
        self.assertIsNone(tree.find('s:script', NS))
        self.assertEqual(tree.find('s:title', NS).text, project['title'])
        self.assertEqual(tree.find('.//s:text', NS).text, layer['text'])

    def test_visibility_changes_actual_raster_and_transparency_is_preserved(self):
        original = self.preset()
        hidden = copy.deepcopy(original)
        for layer in hidden['layers']:
            layer['visible'] = False
        visible_path, empty_path = self.folder/'visible.png', self.folder/'empty.png'
        results = self.actions(dict(command='png', project=original, path=str(visible_path)),
                               dict(command='png', project=hidden, path=str(empty_path)))
        self.assertTrue(all(result['ok'] for result in results), results)
        width, height, rows = rgba_rows(visible_path)
        self.assertEqual((width,height),(128,128))
        self.assertEqual(rows[0][3],0)
        self.assertGreater(rows[64][64*4+3],240)
        self.assertTrue(all(alpha==0 for row in rgba_rows(empty_path)[2] for alpha in row[3::4]))

    def test_real_svg_and_png_import_become_self_contained_raster(self):
        svg = self.folder/'artwork.svg'
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                       '<defs><linearGradient id="g"><stop stop-color="#ff0000"/>'
                       '<stop offset="1" stop-color="#0000ff"/></linearGradient></defs>'
                       '<rect width="64" height="64" fill="url(\'#g\')"/></svg>')
        png = self.folder/'artwork.png'; png.write_bytes(png_bytes(4,2))
        results = self.actions(*(dict(command='import', preset='blank', path=str(path),
                                     output=str(self.folder/(path.stem+'-'+path.suffix[1:]+'.png')))
                                 for path in (svg, png)))
        for value in results:
            self.assertTrue(value['ok'], value)
            layer = value['value']
            self.assertEqual(layer['kind'], 'image')
            self.assertTrue(layer['data_url'].startswith('data:image/png;base64,'))
            embedded = base64.b64decode(layer['data_url'].split(',', 1)[1], validate=True)
            self.assertTrue(embedded.startswith(b'\x89PNG\r\n\x1a\n'))
        embedded = base64.b64decode(results[1]['value']['data_url'].split(',',1)[1])
        self.assertEqual(struct.unpack('>II',embedded[16:24]),(4,2),'PNG import must preserve the original aspect ratio')

    def test_untrusted_svg_references_and_active_content_are_rejected(self):
        payloads = [
            '<!DOCTYPE svg [<!ENTITY secret SYSTEM "file:///etc/passwd">]><svg>&secret;</svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><script>bad()</script></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" onload="bad()"/>',
            '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/icon.png"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><use href="#self" id="self"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url( https://example.test/x )"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:u&#114;l(https://example.test/x)"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:\\75rl(https://example.test/x)"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://example.test/style"</style></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><filter id="f"><feGaussianBlur stdDeviation="999999"/></filter></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" xml:base="https://example.test/"><a href="#icon"/></svg>',
            '<?xml-stylesheet href="https://example.test/style"?><svg xmlns="http://www.w3.org/2000/svg"/>',
        ]
        actions = []
        for index, payload in enumerate(payloads):
            path = self.folder/f'unsafe-{index}.svg'; path.write_text(payload)
            actions.append(dict(command='import', preset='blank', path=str(path)))
        results = self.actions(*actions)
        self.assertTrue(all(not value['ok'] for value in results), results)

    def test_png_bombs_corrupt_data_and_file_limits(self):
        bomb = bytearray(png_bytes()); bomb[16:20] = struct.pack('>I', 1000000)
        paths = []
        for name, data in [('bomb.png', bomb), ('corrupt.png', b'not a png'),
                           ('large.svg', b' ' * 1048577), ('unsupported.jpg', b'fake')]:
            path = self.folder/name; path.write_bytes(data); paths.append(path)
        results = self.actions(*(dict(command='import', preset='blank', path=str(path)) for path in paths))
        self.assertTrue(all(not value['ok'] for value in results), results)
        project = self.preset('blank')
        layer = self.preset()['layers'][0]
        layer.update(kind='image', data_url='data:image/png;base64,'+base64.b64encode(bomb).decode())
        project['layers'] = [layer]
        self.assertFalse(self.actions(dict(command='svg', project=project))[0]['ok'])
        bad_project = self.folder/'oversized.luxicon'; bad_project.write_bytes(b' ' * 3500001)
        self.assertFalse(self.actions(dict(command='open', path=str(bad_project)))[0]['ok'])

    def test_icon_size_set_matches_actual_png_dimensions_and_safe_paths(self):
        folder = self.folder/'exports'
        result = self.actions(dict(command='export', path=str(folder)))[0]
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(result['value']), 11)
        for size in (16,24,32,48,64,96,128,256,512,1024):
            data = (folder/f'icon-{size}.png').read_bytes()
            self.assertEqual(struct.unpack('>II', data[16:24]), (size,size))
        ET.parse(folder/'icon.svg')
        invalid = self.actions(dict(command='export', path=str(folder), basename='../escape'),
                               dict(command='svg', size=0), dict(command='svg', size=2049))
        self.assertTrue(all(not value['ok'] for value in invalid), invalid)

    def test_export_preflights_every_target_and_preserves_existing_files(self):
        folder = self.folder/'existing-export'; folder.mkdir()
        existing = folder/'icon-1024.png'; existing.write_bytes(b'precious existing artwork')
        result = self.actions(dict(command='export',path=str(folder)))[0]
        self.assertFalse(result['ok'],result)
        self.assertIn('already exist',result['error'])
        self.assertEqual(existing.read_bytes(),b'precious existing artwork')
        self.assertEqual([p.name for p in folder.iterdir()],['icon-1024.png'])
        existing.unlink()
        existing.symlink_to(folder/'absent.png')
        self.assertFalse(self.actions(dict(command='export',path=str(folder)))[0]['ok'])
        self.assertTrue(existing.is_symlink())

    def test_compressed_images_have_an_aggregate_decoded_pixel_budget(self):
        image = png_bytes(2048,2048)
        project = self.preset('blank')
        for index in range(3):
            layer = self.preset()['layers'][0]
            layer.update(id=f'image-{index}',kind='image',visible=index==0,
                         data_url='data:image/png;base64,'+base64.b64encode(image).decode())
            project['layers'].append(layer)
        result = self.actions(dict(command='svg',project=project))[0]
        self.assertFalse(result['ok'],result)
        self.assertIn('8 megapixel',result['error'])
        folder = self.folder/'excessive-export'
        result = self.actions(dict(command='export',project=project,path=str(folder)))[0]
        self.assertFalse(result['ok'],result)
        self.assertFalse(folder.exists(),'invalid projects must be rejected before creating export files')

    def test_cli_workflow_without_any_display(self):
        project = self.folder/'cli.luxicon'
        self.assertEqual(self.actions(dict(command='cli', args=['--new',str(project),'ember']))[0]['value'],0)
        output = self.folder/'cli.svg'
        self.assertEqual(self.actions(dict(command='cli', args=['--render',str(project),str(output),'256']))[0]['value'],0)
        self.assertEqual(ET.parse(output).getroot().attrib['width'],'256')
        self.assertEqual(self.actions(dict(command='cli', args=['--render',str(project),str(output),'broken']))[0]['value'],1)
        self.assertEqual(self.actions(dict(command='cli', args=['--unknown']))[0]['value'],2)


if __name__ == '__main__':
    unittest.main()
