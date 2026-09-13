"""Headless Blender asset preparation. Run with -- config.json."""
import json, math, sys, subprocess
from pathlib import Path
import bpy
from mathutils import Vector

cfg = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text())
job = Path(cfg['job_dir'])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=cfg['source'])
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError('No mesh in source')
bpy.ops.object.select_all(action='DESELECT')
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.join()
high = bpy.context.object
high.name = 'Source_High'
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
low = high.copy()
low.data = high.data.copy()
bpy.context.collection.objects.link(low)
low.name = 'Game_LOD0'
def select(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

def tris(obj):
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)

def reduce(obj, target):
    select(obj)
    count = tris(obj)
    if count > target:
        m = obj.modifiers.new('Triangle_budget', 'DECIMATE')
        m.ratio = target / count
        bpy.ops.object.modifier_apply(modifier=m.name)
    # Validate before UV/baking so exporter repair cannot invalidate cached loops.
    obj.data.validate(verbose=True)
    obj.data.update()

source_count = tris(high)
# Rebuild a continuous surface before decimation. Generated meshes can contain
# overlapping/non-manifold fragments that defeat collapse and UV packing.
select(low)
remesh = low.modifiers.new('Continuous_surface', 'REMESH')
remesh.mode = 'VOXEL'
remesh.voxel_size = max(low.dimensions) / 256
remesh.use_smooth_shade = True
bpy.ops.object.modifier_apply(modifier=remesh.name)
reduce(low, int(cfg['target_faces']))
select(low)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.003)
bpy.ops.object.mode_set(mode='OBJECT')
low.data.calc_loop_triangles()
uv = low.data.uv_layers.active.data
uv_area = 0.0
for triangle in low.data.loop_triangles:
    a, b, c = [uv[i].uv for i in triangle.loops]
    uv_area += abs((b-a).cross(c-a)) / 2
if uv_area < .2:
    raise RuntimeError(f'UV packing insufficient: {uv_area:.4f}')
if tris(low) > int(cfg['target_faces']) * 1.05:
    raise RuntimeError('LOD0 failed triangle budget')
size = int(cfg['texture_size'])
texdir = job / 'textures'
texdir.mkdir(exist_ok=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.render.bake.use_selected_to_active = True
scene.render.bake.cage_extrusion = max(low.dimensions) * .02
scene.render.bake.max_ray_distance = max(low.dimensions) * .06
scene.render.bake.margin = 8
mat = bpy.data.materials.new('Game_PBR')
mat.use_nodes = True
low.data.materials.clear()
low.data.materials.append(mat)
for polygon in low.data.polygons:
    polygon.material_index = 0
target = mat.node_tree.nodes.new('ShaderNodeTexImage')
original_materials = list(high.data.materials)
# Bake scalar and base color via emission to remove source lighting.
def bake_channel(name, socket_name, default):
    image = bpy.data.images.new(name, width=size, height=size, alpha=False)
    if name != 'base_color':
        image.colorspace_settings.name = 'Non-Color'
    target.image = image
    mat.node_tree.nodes.active = target
    for index, orig in enumerate(original_materials):
        temp = orig.copy() if orig else bpy.data.materials.new('Temporary')
        temp.use_nodes = True
        high.data.materials[index] = temp
        nodes = temp.node_tree.nodes
        principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
        if output is None:
            output = nodes.new('ShaderNodeOutputMaterial')
        emission = nodes.new('ShaderNodeEmission')
        socket = principled.inputs.get(socket_name) if principled else None
        if socket and socket.is_linked:
            temp.node_tree.links.new(socket.links[0].from_socket, emission.inputs['Color'])
        else:
            value = socket.default_value if socket else default
            emission.inputs['Color'].default_value = (value, value, value, 1) if isinstance(value, (int,float)) else value
        temp.node_tree.links.new(emission.outputs[0], output.inputs['Surface'])
    select(low)
    high.select_set(True)
    bpy.ops.object.bake(type='EMIT')
    for index, orig in enumerate(original_materials):
        high.data.materials[index] = orig
    image.filepath_raw = str(texdir / (name + '.png'))
    image.file_format = 'PNG'
    image.save()
    return image

base = bake_channel('base_color', 'Base Color', (.8,.8,.8,1))
rough = bake_channel('roughness', 'Roughness', .5)
metal = bake_channel('metallic', 'Metallic', 0.)
normal = bpy.data.images.new('normal', width=size, height=size, alpha=False)
normal.colorspace_settings.name = 'Non-Color'
target.image = normal
mat.node_tree.nodes.active = target
select(low)
high.select_set(True)
bpy.ops.object.bake(type='NORMAL')
normal.filepath_raw = str(texdir / 'normal.png')
normal.file_format = 'PNG'
normal.save()
bsdf = mat.node_tree.nodes.get('Principled BSDF')
for image, socket in [(base,'Base Color'), (rough,'Roughness'), (metal,'Metallic')]:
    node = mat.node_tree.nodes.new('ShaderNodeTexImage')
    node.image = image
    mat.node_tree.links.new(node.outputs['Color'], bsdf.inputs[socket])
node = mat.node_tree.nodes.new('ShaderNodeTexImage')
node.image = normal
normalmap = mat.node_tree.nodes.new('ShaderNodeNormalMap')
mat.node_tree.links.new(node.outputs['Color'], normalmap.inputs['Color'])
mat.node_tree.links.new(normalmap.outputs['Normal'], bsdf.inputs['Normal'])
high.hide_render = True
high.hide_set(True)

def export(obj, filename):
    select(obj)
    # Flush geometry after remesh/bake/visibility changes.
    obj.data.validate()
    obj.data.update()
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()
    bpy.ops.export_scene.gltf(filepath=str(job / filename), export_format='GLB', use_selection=True)

export(low, 'model.glb')
counts = {'source': source_count, 'lod0': tris(low)}
for level, ratio in [(1,.5),(2,.25)]:
    obj = low.copy()
    obj.data = low.data.copy()
    bpy.context.collection.objects.link(obj)
    obj.name = 'Game_LOD' + str(level)
    reduce(obj, max(12, int(counts['lod0'] * ratio)))
    export(obj, 'lod' + str(level) + '.glb')
    counts['lod' + str(level)] = tris(obj)
    if tris(obj) > counts['lod0'] * ratio * 1.05:
        raise RuntimeError('LOD simplification failed triangle budget')
    obj.hide_render = True
    obj.hide_set(True)
# A bounding-box collider is deterministic and deliberately documented as coarse.
bounds = [low.matrix_world @ Vector(v) for v in low.bound_box]
minimum = Vector(tuple(min(p[i] for p in bounds) for i in range(3)))
maximum = Vector(tuple(max(p[i] for p in bounds) for i in range(3)))
center = (minimum + maximum) / 2
bpy.ops.mesh.primitive_cube_add(size=1, location=center)
collision = bpy.context.object
collision.name = 'Collision_Box'
collision.dimensions = maximum - minimum
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
export(collision, 'collision.glb')
collision.hide_render = True
collision.hide_set(True)
scene.render.bake.use_selected_to_active = False
scene.world = bpy.data.worlds.new('Studio')
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.18,.18,.18,1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value = .5
extent = max(maximum - minimum)
for loc, power, radius in [((3,-4,5),900,4),((-4,-1,2),650,3),((0,4,3),1000,3)]:
    data = bpy.data.lights.new('Studio_area', 'AREA')
    data.energy = power * .05 * extent * extent
    data.shape = 'DISK'
    data.size = radius * extent / 2
    light = bpy.data.objects.new('Studio_area', data)
    scene.collection.objects.link(light)
    light.location = center + Vector(loc) * extent / 2
    light.rotation_euler = (center - light.location).to_track_quat('-Z','Y').to_euler()
data = bpy.data.cameras.new('Review_camera')
camera = bpy.data.objects.new('Review_camera',data)
scene.collection.objects.link(camera)
scene.camera = camera
data.type = 'ORTHO'
data.ortho_scale = extent * 1.35
scene.render.resolution_x = int(cfg['preview_size'])
scene.render.resolution_y = int(cfg['preview_size'])
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.cycles.samples = 128
scene.view_settings.view_transform = 'AgX'
(job / 'views').mkdir(exist_ok=True)
(job / 'turntable').mkdir(exist_ok=True)
def render(direction, path):
    camera.location = center + Vector(direction).normalized() * extent * 3
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
for name, direction in {'front':(0,-1,0),'back':(0,1,0),'left':(-1,0,0),'right':(1,0,0),'top':(0,0,1),'bottom':(0,0,-1)}.items():
    render(direction, job / 'views' / (name + '.png'))
scene.render.resolution_x = scene.render.resolution_y = 256
for i in range(12):
    angle = i * math.tau / 12
    render((math.sin(angle), -math.cos(angle), .35), job / 'turntable' / ('%03d.png' % i))
subprocess.run(['/usr/bin/ffmpeg','-y','-loglevel','error','-framerate','6','-i',str(job / 'turntable' / '%03d.png'),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(job / 'turntable.mp4')], check=True, timeout=120)
select(low)
for image in (base,rough,metal,normal):
    image.pack()
bpy.ops.wm.save_as_mainfile(filepath=str(job / 'model.blend'))
import bmesh
bm = bmesh.new()
bm.from_mesh(low.data)
geometry_checks = {'finite_vertices': all(math.isfinite(c) for v in bm.verts for c in v.co), 'non_manifold_edges': sum(not e.is_manifold for e in bm.edges), 'degenerate_faces': sum(f.calc_area() < 1e-12 for f in bm.faces), 'uv_layers':len(low.data.uv_layers), 'uv_area':uv_area}
bm.free()
if not geometry_checks['finite_vertices'] or not geometry_checks['uv_layers']:
    raise RuntimeError('Invalid optimized geometry')
report = {'geometry_checks':geometry_checks,'schema_version':1,'triangle_counts':counts,'texture_size':size,'dimensions':list(maximum-minimum),'collision':'axis-aligned bounding box; manual fit recommended','status':'candidate_requires_visual_review','limitations':['Automated decimation is not animation-ready retopology','Unseen surfaces depend on the source generator','Transparent and custom engine shaders require separate authoring','LOD seams and bake projection require visual inspection'],'views':['front','back','left','right','top','bottom'],'blender_version':bpy.app.version_string}
(job / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
