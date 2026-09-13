import { app } from '../../../scripts/app.js';
import { api } from '../../../scripts/api.js';

app.registerExtension({
  name: 'GameAssets.Downloads',
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== 'GameAssetBlenderOptimize') return;
    const previous = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      previous?.apply(this, arguments);
      const bundle = message.text?.find(value => typeof value === 'string' && /^game-assets\/[a-f0-9]{32}\/asset\.zip$/.test(value));
      if (!bundle) return;
      this.gameAssetDirectory = bundle.slice(0, bundle.lastIndexOf('/'));
      if (!this.gameAssetButtons) {
        this.gameAssetButtons = true;
        for (const [label, filename] of [['下载资产 ZIP', 'asset.zip'], ['打开检查报告', 'report.json'], ['播放旋转预览', 'turntable.mp4']]) {
          const widget = this.addWidget('button', label, null, () => {
            const params = new URLSearchParams({ filename, subfolder: this.gameAssetDirectory, type: 'output' });
            window.open(api.apiURL('/view?' + params.toString()), '_blank', 'noopener');
          });
          widget.serialize = false;
        }
        this.setSize(this.computeSize());
      }
      this.setDirtyCanvas(true, true);
    };
  },
});
