"""Validate the four-view workflow's wiring without loading models."""
import json
import unittest
from pathlib import Path

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(Path(__file__).with_name('pixal3d_multiview_4images.json').read_text())
        cls.nodes = {n['id']: n for n in cls.workflow['nodes']}
        cls.links = {l[0]: l for l in cls.workflow['links']}

    def test_links_resolve(self):
        self.assertEqual(len(self.nodes), len(self.workflow['nodes']))
        for link_id, src, slot, dst, port, _ in self.links.values():
            self.assertIn(src, self.nodes)
            self.assertIn(dst, self.nodes)
            self.assertEqual(self.nodes[dst]['inputs'][port]['link'], link_id)
            self.assertIn(link_id, self.nodes[src]['outputs'][slot]['links'])

    def test_four_distinct_views_condition_one_model(self):
        for i, view in enumerate(('front', 'left', 'back', 'right')):
            port = next(p for p in self.nodes[324]['inputs'] if p['name'] == view)
            source = self.nodes[self.links[port['link']][1]]
            self.assertEqual(source['id'], 400 + i)
            self.assertEqual(source['widgets_values_named']['image'], f'pixal_mv_{view}.png')
        self.assertEqual(self.nodes[319]['widgets_values'][0], 'pixal3d_multiview_int8_convrot.safetensors')

    def test_resource_defaults_and_output(self):
        self.assertEqual(self.nodes[94]['widgets_values_named']['target_resolution'], 1024)
        self.assertEqual(self.nodes[186]['widgets_values_named']['target_face_count'], 50000)
        self.assertEqual(self.nodes[372]['widgets_values_named']['filename_prefix'], '3d/Pixal3D_multiview')
        self.assertNotIn('GeminiImage2Node', {n['type'] for n in self.nodes.values()})

if __name__ == '__main__':
    unittest.main()
