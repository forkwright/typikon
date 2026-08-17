+++
title = "Dyes"
description = "Fixture page exercising the leather skin's dye-entry / swatch content classes (forkwright/typikon#55)."
+++

This page exists to prove the leather skin's own content-authoring classes
(`.dye-entry-*`, `.dye-swatch`, `.swatch-*`, `.dye-marks`) still render once
moved out of core and opted into via `consumer_css` — no core template emits
these; they are raw HTML in this fixture's own markdown, exactly how a real
consumer would author them.

<div class="dye-entry dye-entry-aima">
  <h2>Αἷμα <span class="dye-greek">(aima)</span></h2>
  <span class="dye-swatch swatch-aima"></span>
  <p class="ingredient-note">Blood-red, iron-mordanted.</p>
</div>

<div class="dye-entry dye-entry-thanatochromia">
  <h2>Θανατοχρωμία <span class="dye-greek">(thanatochromia)</span></h2>
  <span class="dye-swatch swatch-thanatochromia"></span>
  <p class="ingredient-note">Death-color, deep violet-black.</p>
</div>

<div class="dye-entry dye-entry-aporia">
  <h2>Ἀπορία <span class="dye-greek">(aporia)</span></h2>
  <span class="dye-swatch swatch-aporia"></span>
  <p class="ingredient-note">Impasse-green, the dye that can't decide.</p>
</div>

<div class="dye-entry dye-entry-natural">
  <h2>Natural <span class="dye-greek">(undyed)</span></h2>
  <span class="dye-swatch swatch-natural"></span>
  <p class="ingredient-note">Unmordanted, the leather's own color.</p>
</div>

<div class="dye-marks">
  <span class="mark mark-aima"></span>
  <span class="mark mark-thanatochromia"></span>
  <span class="mark mark-aporia"></span>
</div>
