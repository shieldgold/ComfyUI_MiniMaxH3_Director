import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

// Exercise the production editor methods without loading ComfyUI's browser runtime.
const source = readFileSync(new URL('../web/js/minimax_timeline.js', import.meta.url), 'utf8');
const names = ['onExportDurationChanged', 'syncExportDurationUI', 'getMaxExportFrames', 'getExportFrameTotal', 'getFrameRate', 'syncFrameRateUI',
    '_clipFrameCountAtFps', '_timelineFrameCountAtFps', '_rescaleSegmentsForTotal',
    '_syncClipFrameCountsForFps', '_resampleFrameMapForFps', '_resampleTimelineForFrameRate',
    'onFrameRateChanged', '_prepareVideoFrames'];
const methods = names.map(name => {
    const match = source.match(new RegExp(`\\n    (?:async )?${name}\\([^]*?\\n    }`));
    assert.ok(match, `Production method ${name} exists`);
    return match[0];
});
const context = { console, t: (key, args) => JSON.stringify(args), coerceTimelineFps: x => Number(x),
    clamp: (x, lo, hi) => Math.min(hi, Math.max(lo, x)),
    normalizeFrameMapEntry: x => x, deletedSourceRanges: x => x.deletedSourceRanges || [],
    THUMB_PREFETCH_BATCH: 4, inputViewUrl: x => x, resolveOutputDimensions: () => ({}) };
const Editor = vm.runInNewContext(`(class {${methods.join('\n')}})`, context);
function fixture(fps = 54.19, total = 1044, cap = 124) {
    const e = new Editor();
    e.timeline = { frameRate: fps, totalFrames: total, output: { maxExportFrames: cap },
        video: {}, videoClips: [{ nativeFps: 54.186851211, nativeFrameCount: 1044, duration: 19.266667 }],
        segments: [{ start: 0, length: total, frameCount: total }] };
    e.currentFrame = 54;
    e.totalFramesWidget = { value: total };
    e.getTotalFrames = () => e.totalFramesWidget.value;
    e.getVideoClips = () => e.timeline.videoClips;
    e.isFl2vMode = e.isImageBatch = e.isGenMode = () => false;
    e.hasVideo = () => true;
    e.getFrameMap = () => e.map || [];
    e.getFrameMapEntry = i => e.map?.[i] || { clip: 0, frame: i };
    e.setFrameMap = map => { e.map = map; };
    e.setSparseVideoFrames = n => { e.totalFramesWidget.value = n; };
    for (const name of ['_syncPrimaryVideoFromClips', '_prefetchSegmentThumbs', 'syncOutputUIFromTimeline',
        'updateVideoNameLabel', 'updateOutputPreview', 'scheduleRender', 'commit']) e[name] = () => {};
    return e;
}
test('54.19fps to 24 preserves source duration, segment boundaries and export cap seconds', () => {
    const e = fixture();
    e.onFrameRateChanged(24);
    assert.equal(e.getFrameRate(), 24);
    assert.equal(e.getTotalFrames(), 462);
    assert.equal(e.timeline.segments[0].length, 462);
    assert.equal(e.getMaxExportFrames(), 55);
    assert.equal(e.getExportFrameTotal(), 55);
    assert.ok(Math.abs(55 / 24 - 124 / 54.19) < 1 / 24);
    e.onFrameRateChanged(24); // Idempotent button and input change events.
    assert.equal(e.getMaxExportFrames(), 55);
});
test('an unlimited export remains unlimited; a two-second source is not extended', () => {
    const e = fixture(54.19, 124, 0);
    e.onFrameRateChanged(24);
    assert.equal(e.getTotalFrames(), 55);
    assert.equal(e.getMaxExportFrames(), 0);
});
test('resampling an edited timeline retains a removed source interval', () => {
    const e = fixture(54, 108, 0);
    e.map = Array.from({length:108}, (_,i) => ({clip:0, frame:i < 54 ? i : i+54}));
    e.onFrameRateChanged(24);
    assert.equal(e.map.length,48);
    assert.equal(e.map[23].frame,23);
    assert.equal(e.map[24].frame,48); // Jump over deleted source second.
    assert.equal(e.map[47].frame,71);
});
test('video import keeps the selected timeline FPS instead of adopting native FPS', async () => {
    const e = fixture(24);
    e.videoNameEl = {};
    e.probeVideoFile = async () => ({native_fps:54.186851211, frame_count:1044, duration:19.266667,width:720,height:1280});
    e.probeVideoMetadata = async () => ({});
    const result = await e._prepareVideoFrames({fileName:'source.mp4',relPath:'source.mp4',statusPrefix:'Import'});
    assert.equal(e.getFrameRate(),24);
    assert.equal(result.totalFrames,462);
    assert.equal(result.meta.nativeFrameCount,1044);
});

test('seconds cap rounds to playable frames, supports unlimited and rejects invalid input', () => {
    const e = fixture(24, 240, 0);
    e.onOutputField = (key, value) => { e.timeline.output[key] = value; };
    e.onExportDurationChanged('5');
    assert.equal(e.getMaxExportFrames(),120);
    e.onExportDurationChanged('-1');
    assert.equal(e.getMaxExportFrames(),120);
    e.onExportDurationChanged('invalid');
    assert.equal(e.getMaxExportFrames(),120);
    e.onExportDurationChanged('0.001');
    assert.equal(e.getMaxExportFrames(),1);
    e.onExportDurationChanged('0');
    assert.equal(e.getMaxExportFrames(),0);
    e.outDurationInfo = {};
    e.syncExportDurationUI();
    assert.deepEqual(JSON.parse(e.outDurationInfo.textContent),{frames:240,seconds:'10.00'});
});

test('uncommitted FPS input cannot change playback rate before resampling', () => {
    const e = fixture(24, 240, 120);
    e.fpsInput = {value:'54.19'};
    assert.equal(e.getFrameRate(),24);
    e.onFrameRateChanged(e.fpsInput.value);
    assert.equal(e.getTotalFrames(),542);
    assert.equal(e.getMaxExportFrames(),271);
    e.onFrameRateChanged(24);
    assert.equal(e.getTotalFrames(),240);
    assert.equal(e.getMaxExportFrames(),120);
});
