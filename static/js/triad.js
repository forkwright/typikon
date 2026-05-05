// Cycling triad mark — initial cycle through three Greek terms, then settle.
// Originally inline in ardent-site's index.md; extracted to satisfy strict CSP.
//
// Markup contract (rendered by templates/index.html):
//   <a class="triad-mark cycling" id="triad">
//     <span class="triad-word triad-1"><span class="greek">…</span><span class="english">…</span></span>
//     <span class="triad-dot">·</span>
//     <span class="triad-word triad-2">…</span>
//     <span class="triad-dot">·</span>
//     <span class="triad-word triad-3">…</span>
//   </a>
//
// CSS handles the cycling animation (6s total, 3 × 1.8s + buffer). At the end
// of the cycle, swap `.cycling` for `.settled` so the three words hold steady.

(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var triad = document.getElementById('triad');
    if (!triad) return;
    setTimeout(function () {
      triad.classList.remove('cycling');
      triad.classList.add('settled');
    }, 6000);
  });
})();
