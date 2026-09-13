# Server Game Asset Pipeline Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for bounded implementation and review tasks.

**Goal:** GPU3 serves an image-to-game-asset candidate workflow with Blender optimization, baked materials, LOD, collision mesh, six views, turntable and API-accessible bundle.

**Architecture:** Standalone plugin under integrations/game_assets installed independently of H3. Existing Pixal3D image generation outputs FILE_3D_GLB to a subprocess-backed Blender node. A job directory records progress and failures; ComfyUI remains the queue/API. No extra public service.

**Tech Stack:** ComfyUI legacy node API, Python standard library, Blender 4.0+ CPU Cycles, GLB, JSON, ZIP.

- [x] Implement runner: relative paths confined to Comfy input/output/temp, validate GLB magic and size, bound triangle/texture parameters, isolated UUID job directory, exclusive process lock, timeout/cancel process-group termination, atomic status and verified final manifest. Test traversal, symlinks, bad configuration, cancellation, corrupt outputs.
- [x] Implement Blender stage: import GLB, retain source for selected-to-active baking, decimate to target triangles, UV unwrap, bake base color/roughness/metallic/normal, export LOD0/1/2 and convex collision, pack editable .blend, render six directions and turntable contact frames, report actual counts and visual-review limitations.
- [x] Implement ComfyUI node and workflow: FILE_3D input from original template, bounded settings, returned GLB/report/bundle and preview images. CLI uploads image, submits fixed workflow, persists prompt ID without automatic retry on uncertain submission, resumes status polling using saved ID.
- [x] Install Blender, deploy plugin to GPU3 only, backup/drop-in startup config, verify queue empty before restart; no other service restart.
- [x] Validate unit tests then full image-to-GLB generation and Blender stage with original axe. Check downloaded GLBs, LOD counts, embedded texture decoding, ZIP contents, six views and client workflow registration. Review implementation, document real results and rollback, commit and push personal branch.
