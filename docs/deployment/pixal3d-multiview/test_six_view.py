import importlib.util
import math
from pathlib import Path
import unittest
spec = importlib.util.spec_from_file_location('cameras', Path(__file__).parent/'six_view_node/cameras.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)

class SixViewTests(unittest.TestCase):
    def test_six_distinct_orthonormal_cameras(self):
        matrices = c.camera_matrices(c.VIEWS, 20)
        for m in matrices:
            cols = [[m[i][j] for i in range(3)] for j in range(3)]
            for i in range(3):
                for j in range(3):
                    self.assertAlmostEqual(sum(a*b for a,b in zip(cols[i],cols[j])), float(i==j))
            # Camera forward (-local Z) points toward the origin.
            d = math.sqrt(sum(m[i][3]**2 for i in range(3)))
            for i in range(3): self.assertAlmostEqual(m[i][2],m[i][3]/d)
        expected=[(0,-1,0),(1,0,0),(0,1,0),(-1,0,0),(0,0,1),(0,0,-1)]
        for m,d in zip(matrices,expected):
            for i in range(3):self.assertAlmostEqual(m[i][2],d[i])
        self.assertAlmostEqual(matrices[4][1][1],1)
        self.assertAlmostEqual(matrices[5][1][1],-1)
    def test_invalid_inputs(self):
        for f in (0,180,float('nan')):
            with self.assertRaises(ValueError):c.camera_matrices(c.VIEWS,f)
        with self.assertRaises(ValueError):c.camera_matrices(['top'],20)
        for sizes in ([0,1],[2,3],[]):
            with self.assertRaises(ValueError):c.batch_size_for_views(sizes)
    def test_broadcast_and_optional_views(self):
        self.assertEqual(c.batch_size_for_views([1,3,3,1]),3)
        self.assertEqual(len(c.camera_matrices(['front','top'],20)),2)
if __name__=='__main__':unittest.main()
