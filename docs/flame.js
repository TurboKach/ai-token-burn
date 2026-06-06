/* 8-bit burning flame for the masthead — the classic DOOM fire effect.
   Algorithm + palette: https://github.com/filipedeschamps/doom-fire-algorithm
   (MIT). A low-res heat grid is seeded along the bottom with a flame-shaped
   profile (hot center, cold edges), spread upward with random decay each frame,
   mapped through the 37-colour fire ramp, and drawn 1:1 into a small canvas that
   CSS upscales with image-rendering:pixelated for crisp chunky pixels. */
(() => {
  const canvas = document.getElementById('flame-canvas');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;

  // Coldest (transparent) → hottest (white). Index 0 is treated as empty.
  const PALETTE = [
    [7,7,7],[31,7,7],[47,15,7],[71,15,7],[87,23,7],[103,31,7],[119,31,7],
    [143,39,7],[159,47,7],[175,63,7],[191,71,7],[199,71,7],[223,79,7],
    [223,87,7],[223,87,7],[215,95,7],[215,95,7],[215,103,15],[207,111,15],
    [207,119,15],[207,127,15],[207,135,23],[199,135,23],[199,143,23],
    [199,151,31],[191,159,31],[191,159,31],[191,167,39],[191,167,39],
    [191,175,47],[183,175,47],[183,183,47],[183,183,55],[207,207,111],
    [223,223,159],[239,239,199],[255,255,255],
  ];
  const MAX = PALETTE.length - 1; // 36

  // Bottom-row heat profile: a bell peaking at the centre and falling to 0 at
  // the edges, so the fire burns as a single flame instead of a wall.
  const SRC = new Array(W);
  const cx = (W - 1) / 2;
  const EDGE = 0.62;                          // outer columns stay cold → flame, not wall
  for (let x = 0; x < W; x++) {
    const d = Math.abs(x - cx) / cx;          // 0 centre … 1 edge
    SRC[x] = d > EDGE ? 0 : Math.round(MAX * (1 - Math.pow(d / EDGE, 2)));
  }

  const fire = new Uint8Array(W * H);       // intensity grid, starts cold
  const img = ctx.createImageData(W, H);

  function spread(from) {
    const intensity = fire[from];
    if (intensity === 0) {
      fire[from - W] = 0;
      return;
    }
    const decay = (Math.random() * 3) | 0;       // 0..2 — fades upward so tongues taper
    const r = Math.random();
    const drift = r < 0.16 ? -1 : r > 0.84 ? 1 : 0; // mostly straight up, occasional sway
    const to = from - W + drift;
    if (to >= 0) fire[to] = Math.max(0, intensity - decay); // clamp: Uint8 must not underflow
  }

  function step() {
    for (let x = 0; x < W; x++) fire[(H - 1) * W + x] = SRC[x]; // re-seed source
    for (let x = 0; x < W; x++)
      for (let y = 1; y < H; y++) spread(y * W + x);
  }

  function render() {
    const d = img.data;
    for (let i = 0; i < fire.length; i++) {
      const v = fire[i], o = i * 4, c = PALETTE[v];
      d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2];
      d[o + 3] = v === 0 ? 0 : 255;          // cold pixels are transparent
    }
    ctx.putImageData(img, 0, 0);
  }

  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) {
    for (let i = 0; i < 48; i++) step();      // settle to a stable frame, no loop
    render();
    return;
  }

  let raf = 0, last = 0;
  function frame(t) {
    if (t - last >= 33) { step(); render(); last = t; } // ~30fps, retro cadence
    raf = requestAnimationFrame(frame);
  }
  // Pause when the tab is hidden so the loop costs nothing in the background.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
    else if (!raf) { last = 0; raf = requestAnimationFrame(frame); }
  });
  raf = requestAnimationFrame(frame);
})();
