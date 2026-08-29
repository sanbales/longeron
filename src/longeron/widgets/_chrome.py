"""The shared chrome for widget control surfaces (CSS only, ``lgw-*``).

Widget front-ends float their controls over a canvas.  This module is
the house stylesheet for that surface: design tokens bridged from the
JupyterLab theme (with light fallbacks for standalone pages), toggle
pills backed by real checkboxes, slim filled-track sliders, veiled
panels with a collapse transition, a search field with a result list,
breadcrumb chips, and legend rows.  A widget opts in by adding the
``lgw`` class next to its root class and prepending
:data:`CONTROL_CSS` to its ``_css``.

Design notes (the artifactory-design vocabulary): ``strategy
(restrained)`` -- the chrome stays neutral and hands its single accent
to the JupyterLab brand color; every control state (hover, checked,
pressed, focus-visible) derives from the token slots via ``color-mix``
instead of new colors; motion is ``cadence(restrained)`` -- 100-220ms
ease-out state transitions, nothing continuous.  Focus rings are real
``:focus-visible`` outlines; pills wrap real ``<input>`` elements so
keyboard access and semantics come from the platform.
"""

from __future__ import annotations

__all__ = ["CONTROL_CSS"]

#: the control-surface stylesheet; every rule derives from the token
#: slots declared on ``.lgw`` (JupyterLab vars with light fallbacks)
CONTROL_CSS = """
.lgw {
  --lgw-bg: var(--jp-layout-color1, #f6f6f4);
  --lgw-ink: var(--jp-ui-font-color1, #2f3237);
  --lgw-mute: var(--jp-ui-font-color2, #757a82);
  --lgw-line: var(--jp-border-color1, #d8dade);
  --lgw-accent: var(--jp-brand-color1, #1d7fd1);
  --lgw-veil: color-mix(in srgb, var(--lgw-bg) 72%, transparent);
  --lgw-track: color-mix(in srgb, var(--lgw-ink) 18%, transparent);
  --lgw-ease: cubic-bezier(0.25, 1, 0.5, 1);
}

/* --- veiled panel with a collapsing body (grid-rows transition) --- */
.lgw-panel {
  position: absolute; top: 8px; left: 8px; z-index: 3; width: 198px;
  max-height: calc(100% - 16px); overflow-y: auto;
  overscroll-behavior: contain;
  background: var(--lgw-veil);
  -webkit-backdrop-filter: blur(12px) saturate(1.15);
  backdrop-filter: blur(12px) saturate(1.15);
  border: 1px solid var(--lgw-line); border-radius: 10px;
  padding: 4px 10px 10px; color: var(--lgw-ink);
  font-size: 11px; line-height: 1.45; user-select: none;
  box-sizing: border-box;
}
.lgw-panel.closed { padding-bottom: 4px; }
.lgw-panel-head { display: flex; align-items: center; }
.lgw-panel-toggle {
  font-family: inherit; font-weight: 600; color: var(--lgw-mute);
  background: none; border: 0; padding: 4px 2px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px;
  letter-spacing: 0.06em; text-transform: uppercase; font-size: 9.5px;
  transition: color 120ms var(--lgw-ease);
}
.lgw-panel-toggle:hover { color: var(--lgw-ink); }
.lgw-panel-toggle:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: 1px;
  border-radius: 4px;
}
.lgw-caret {
  display: inline-block; transition: transform 200ms var(--lgw-ease);
}
[aria-expanded="false"] > .lgw-caret { transform: rotate(-90deg); }
.lgw-panel-body {
  display: grid; grid-template-rows: 1fr;
  transition: grid-template-rows 220ms var(--lgw-ease);
}
.closed > .lgw-panel-body { grid-template-rows: 0fr; }
.lgw-panel-body > div { overflow: hidden; min-height: 0; }
.lgw-heading {
  margin: 9px 0 4px; font-size: 9px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--lgw-mute);
}
.lgw-note { color: var(--lgw-mute); font-size: 10px; margin-top: 3px; }

/* --- toggle pills: a real checkbox inside; the kind-color chip and
   the tinted fill make the pressed state unmistakable --------------- */
.lgw-pills { display: flex; flex-wrap: wrap; gap: 4px; }
.lgw-pill {
  --pill: var(--c, var(--lgw-ink));
  position: relative; display: inline-flex; align-items: center;
  gap: 5px; padding: 2px 9px; border: 1px solid var(--lgw-line);
  border-radius: 999px; background: transparent;
  color: var(--lgw-mute); cursor: pointer;
  font-family: inherit; font-size: 10.5px; line-height: 1.5;
  transition: background 120ms var(--lgw-ease),
    border-color 120ms var(--lgw-ease), color 120ms var(--lgw-ease);
}
.lgw-pill:hover {
  border-color: color-mix(in srgb, var(--lgw-ink) 35%, var(--lgw-line));
}
.lgw-pill:active {
  background: color-mix(in srgb, var(--pill) 24%, transparent);
}
.lgw-pill input {
  position: absolute; opacity: 0; width: 1px; height: 1px; margin: 0;
  pointer-events: none;
}
.lgw-chip {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--pill); opacity: 0.35;
  transition: opacity 120ms var(--lgw-ease);
}
.lgw-pill:has(input:checked), .lgw-pill[aria-pressed="true"] {
  background: color-mix(in srgb, var(--pill) 15%, transparent);
  border-color: color-mix(in srgb, var(--pill) 50%, var(--lgw-line));
  color: var(--lgw-ink);
}
.lgw-pill:has(input:checked) .lgw-chip { opacity: 1; }
.lgw-pill:has(input:focus-visible), .lgw-pill:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: 1px;
}

/* --- sliders: slim track, filled progress (--p in 0..1), round thumb
   with press feedback ---------------------------------------------- */
.lgw-slider {
  -webkit-appearance: none; appearance: none; height: 4px; flex: 1;
  min-width: 60px; border-radius: 2px; margin: 6px 0; cursor: pointer;
  background: linear-gradient(to right,
    var(--lgw-accent) calc(var(--p, 0) * 100%),
    var(--lgw-track) calc(var(--p, 0) * 100%));
}
.lgw-slider:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: 4px;
}
.lgw-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 13px; height: 13px;
  border-radius: 50%; background: var(--lgw-accent);
  border: 2px solid var(--lgw-bg);
  box-shadow: 0 0 0 1px var(--lgw-line);
  transition: transform 100ms var(--lgw-ease);
}
.lgw-slider:active::-webkit-slider-thumb { transform: scale(1.3); }
.lgw-slider::-moz-range-thumb {
  width: 11px; height: 11px; border-radius: 50%;
  background: var(--lgw-accent); border: 2px solid var(--lgw-bg);
  box-shadow: 0 0 0 1px var(--lgw-line);
  transition: transform 100ms var(--lgw-ease);
}
.lgw-slider:active::-moz-range-thumb { transform: scale(1.3); }
.lgw-row { display: flex; align-items: center; gap: 8px; }
.lgw-row > span:first-child {
  color: var(--lgw-mute); font-size: 10.5px;
}
.lgw-value {
  margin-left: auto; color: var(--lgw-mute); font-size: 10px;
  font-variant-numeric: tabular-nums; min-width: 3ch;
  text-align: right;
}

/* --- floating bars and breadcrumb chips --------------------------- */
.lgw-morphbar {
  position: absolute; top: 8px; left: 50%;
  transform: translateX(-50%); z-index: 2;
  display: flex; align-items: center; gap: 8px; padding: 3px 12px;
  border: 1px solid var(--lgw-line); border-radius: 999px;
  background: var(--lgw-veil);
  -webkit-backdrop-filter: blur(12px) saturate(1.15);
  backdrop-filter: blur(12px) saturate(1.15);
  font-size: 9.5px; letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--lgw-mute); user-select: none;
}
.lgw-morphbar .lgw-slider { width: 132px; flex: none; }
.lgw-morphbar span { transition: color 160ms var(--lgw-ease); }
.lgw-morphbar span.on { color: var(--lgw-ink); font-weight: 600; }
.lgw-chipbar {
  position: absolute; top: 42px; left: 50%;
  transform: translateX(-50%); z-index: 2;
  display: flex; gap: 6px; max-width: 72%;
}
.lgw-crumb {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 10px; border: 1px solid var(--lgw-line);
  border-radius: 999px; background: var(--lgw-veil);
  -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);
  color: var(--lgw-ink); font-family: inherit; font-size: 10.5px;
  cursor: pointer; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;
  transition: border-color 120ms var(--lgw-ease),
    background 120ms var(--lgw-ease);
}
.lgw-crumb:hover {
  border-color: color-mix(in srgb, var(--lgw-ink) 35%, var(--lgw-line));
}
.lgw-crumb:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: 1px;
}
.lgw-crumb-static { cursor: default; color: var(--lgw-mute); }

/* --- search: type-ahead field + option list ----------------------- */
.lgw-search { margin-top: 6px; }
.lgw-search input {
  font-family: inherit; font-size: 11px; width: 100%;
  box-sizing: border-box; color: var(--lgw-ink);
  background: color-mix(in srgb, var(--lgw-ink) 4%, transparent);
  border: 1px solid var(--lgw-line); border-radius: 6px;
  padding: 4px 8px;
  transition: border-color 120ms var(--lgw-ease);
}
.lgw-search input::placeholder { color: var(--lgw-mute); opacity: 1; }
.lgw-search input:hover {
  border-color: color-mix(in srgb, var(--lgw-ink) 35%, var(--lgw-line));
}
.lgw-search input:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: 1px;
}
.lgw-search-list {
  display: flex; flex-direction: column; gap: 1px; margin-top: 2px;
  max-height: 150px; overflow-y: auto;
}
.lgw-option {
  font-family: inherit; font-size: 10.5px; text-align: left;
  color: var(--lgw-ink); background: none; border: 0;
  border-radius: 5px; padding: 3px 6px; cursor: pointer;
}
.lgw-option:hover, .lgw-option[aria-selected="true"] {
  background: color-mix(in srgb, var(--lgw-accent) 14%, transparent);
}
.lgw-option:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: -1px;
}
.lgw-option-id {
  display: block; color: var(--lgw-mute); font-size: 9px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* --- legend -------------------------------------------------------- */
.lgw-legend {
  position: absolute; right: 8px; bottom: 26px; z-index: 2;
  background: var(--lgw-veil);
  -webkit-backdrop-filter: blur(12px) saturate(1.15);
  backdrop-filter: blur(12px) saturate(1.15);
  border: 1px solid var(--lgw-line); border-radius: 10px;
  padding: 2px 10px 6px; color: var(--lgw-ink);
  font-size: 10px; line-height: 1.5; user-select: none;
}
.lgw-legend.closed { padding-bottom: 2px; }
.lgw-key { display: flex; align-items: center; gap: 6px; margin: 1px 0; }
.lgw-dot {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--lgw-mute);
}
.lgw-line {
  width: 16px; border-top: 2px solid var(--lgw-mute); flex: none;
}
.lgw-cue { margin-top: 5px; color: var(--lgw-mute); }
"""
