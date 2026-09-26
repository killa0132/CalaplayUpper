# Custom background images: preview block and timeline entries never receive the modded row

**Audience:** CalaPlayer developer. **Scope:** a UE 5.7 / 5.7.4 galgame-maker title, shipped and cooked, no source access.
**Nature of this document:** read-only runtime evidence from an installed mod. No game files were modified. We are
asking whether there is a cleaner Blueprint-side fix than the runtime workaround we are currently forced to use.

---

## 1. Summary

Our mod container appends exactly one row to `DA_Backgrounds` and ships one texture plus one
`MaterialInstanceConstant` preview material for it, following your public advice. The appended data is **correct and
fully visible to the engine**: the row is present in `DA_Backgrounds.BackgroundMap`, in
`WBP_Editor_C.BackgroundNamesPreviews`, in `WBP_DetailsPanel.BackgroundNamesPreviews`, and its dropdown list entry is
built exactly like the built-in ones — which is why the dropdown thumbnails work. The **preview block** and the
**timeline entries**, however, never receive that material: their receiving widgets still hold their design-time
default material or `null`, and the panel property that the last hop would need (`WBP_DetailsPanel.BackgroundsData`)
is empty at runtime. Crucially, **the same is true for the game's own built-in backgrounds** — the chain does not run
this last hop for them either. The failure is therefore not caused by our row, and cannot be fixed from the static
asset side.

---

## 2. Reproduction environment

| Item | Value |
|---|---|
| Game | CalaPlayer, UE 5.7.4, build `++UE5+Release-5.7-CL-51494982`, cooked Shipping |
| Mod install | Static IoStore patch container `CalaPlayer-Windows_P.{pak,ucas,utoc}` in `CalaPlayer/Content/Paks/` |
| Mod content | Exactly **one appended background row**, name `bg_dark` (pure ASCII, `key == object name`) |
| `DA_Backgrounds.BackgroundMap` | **166 entries** = 165 built-in + 1 appended |
| Patch `ImportMap` | **335 imports** = 333 original + 2 appended (texture + `MaterialInstanceConstant`) |
| Per-row assets | One texture package (`/Game/CalaPlayer/Backgrounds/bg_dark`) + one MIC (`MI_bg_dark`) |
| Entry point used | Main menu → CREATE tab → Create editor |
| Read-only proof | `sha256` of `CalaPlayer-Windows_P.{pak,ucas,utoc}` and `Saved/SaveGames/Scenarios.sav` **identical before and after** the whole probe session |

### Method / reproducibility

1. **Live reflection dump from the running process.** `jmap_dumper` (`--engine-version 5.7 --stats --all`) dumps the
   live `GUObjectArray` including CDOs and property values; the game process was suspended for the duration of the
   dump and resumed afterwards so the object graph stayed consistent. This is a pure read — it never writes into the
   game.
2. **A/B/A experiment via a Frida-based reflection driver.** UFunction addresses are resolved **by name** from the
   class chain at runtime (no hard-coded offsets); every call is guarded by `IsValid()` plus class/name checks, and
   the call frame is generated from the engine's own property table. All calls are process-local; restarting the game
   restores everything.
3. **Visual measurement.** `PrintWindow` screenshots of the game window before and after each call, compared by
   changed-pixel count. All counts below are from the same live session on the same window geometry.
4. **Pixel counts** are therefore directly comparable within this session. The ~18-pixel floor is the 3D background
   animation in the editor viewport (it changes even with no UI call at all).

---

## 3. Measured object state (6 groups, read from the live process)

The same background name is present in **every** lookup table, and the currently selected step's background name
**already is the modded one** — yet every *receiving* widget still holds its design-time default.

| # | Object / property | Observed value |
|---|---|---|
| 1 | `DA_Backgrounds` (live instance) — `BackgroundMap` | **166 entries**; last entry `bg_dark -> /Game/CalaPlayer/UI/EditorUI/Sprites/Backgrounds/MI_bg_dark` |
| 1b | `DA_Backgrounds` — sibling arrays `Backgrounds` / `Previews` | **0 / 0 entries** (matches the shipped asset; nothing populates them at runtime) |
| 2 | `WBP_Editor_C` — `BackgroundNamesPreviews` | **166 entries**, includes `bg_dark -> MI_bg_dark` |
| 3 | `WBP_DetailsPanel` — `BackgroundNamesPreviews` | **166 entries**, includes the modded row |
| 3b | `WBP_DetailsPanel` — **`BackgroundsData`** | **0 entries** (empty) |
| 3c | `WBP_DetailsPanel` — `BackgroundChange` | **`bg_dark`** in the session we measured — the panel already believes the modded background is selected. (On a freshly created scenario the field is unset until a background is picked, which is expected.) |
| 4 | `BP_TimelineSlotObject_C_2147482266` (the object referenced by `WBP_Editor_C.SelectedTimelineObject`, i.e. the current step) — `TimelineStep.BackgroundChanges.BackgroundChange` | **`bg_dark`** |
| 5 | `WBP_BackgroundPreview_C` (2 live instances — the "Preview block") — `PreviewMaterial` | a `MaterialInstanceDynamic` whose `Parent` = `MMI_BackgroundPreview` (→ `MM_BackgroundPreviewBase`), with **empty** `ScalarParameterValues` / `TextureParameterValues` — i.e. it renders the material's own default, not any background row |
| 6 | `WBP_TimelineTrackHeaderItem_C` (4 live instances) — `BackgroundDynamicMaterial` | **`null` for all four** |
| 6b | `WBP_SubslotContent_C` (live) — `BackgroundMaterial` | `MMI_SubslotContentBackground` (**design-time default**) |

Two supporting checks:

* **The modded material itself is healthy.** `MI_bg_dark`: `Parent` = `MMI_BackgroundSelector`,
  `SourceTexture` = `/Game/CalaPlayer/Backgrounds/bg_dark`, all **6 scalar parameters authored**. It is a normal,
  loadable MIC.
* **The modded row is structurally identical to the built-ins.** All **166** dropdown list items
  (`WBP_CharacterListItem_C_*`, one per background row) hold a MID created from that row's `Preview` material; ours
  is `MID_MI_bg_dark_178` next to built-ins such as `MID_MI_BackgroundPreview_051_64` — same construction, same
  mounting point, same naming pattern.

So the difference between the working dropdown path and the broken preview/timeline path is **not** the data and
**not** the material.

---

## 4. The decisive experiment (A/B/A, pixel-measured)

Each row is one `ProcessEvent` call issued against the live widget from the same session, with a `PrintWindow`
screenshot immediately before and after.

| Action (called on the live widget) | Changed pixels | Interpretation |
|---|---|---|
| `WBP_BackgroundPreview_C:SetPlaceholder()` | **0** | The Blueprint entry point is a **no-op when called from outside** |
| `WBP_BackgroundPreview_C:SetImage(<MaterialInstanceConstant>)` | **0** | No visual change; only the MID's scalar array went from empty to populated, so internally `SetDynamicMaterial` ran but the brush was not replaced |
| native `UImage::SetBrushFromMaterial(<MI_bg_dark>)` on the widget's `Image_Preview` | **86,790** | **Both preview blocks immediately display the modded image** — see `01_before_editor_preview_default.png` vs `02_after_push_our_MI.png` |
| native `UImage::SetBrushFromMaterial(<MMI_BackgroundPreview>)` (revert) | **86,787** | Fully symmetric and reversible — the two calls differ by 3 pixels of animation noise |
| **`WBP_DetailsPanel_C:SetBackgroundEditor(<the currently selected step object>)`** — the game's own "step selected → populate panel" entry point | **18** | **This is the key evidence:** the game's own chain does not perform this last hop. 18 pixels equals the 3D-scene animation noise floor, i.e. no UI change at all. |

The last row is the whole point: we invoked the game's *own* update entry point with the *correct*, already-modded
argument, and nothing in the preview block moved. That is independent of our data.

---

## 5. Conclusion

The root cause is none of the following:

* **not** the appended row — it is present in `BackgroundMap` and in both `BackgroundNamesPreviews` maps (166 / 166 / 166);
* **not** a naming or path mismatch — `key == object name`, the package path is the standard one, and the current
  step's background name **is already `bg_dark`** in both the details panel and the timeline slot object;
* **not** a stale cache or asset-load failure — `MI_bg_dark` loads, resolves its `SourceTexture`, and is consumed
  normally by `CreateDynamicMaterialInstance` in the dropdown path.

The root cause is that **nothing ever pushes the selected background's `Preview` material into
`WBP_BackgroundPreview.PreviewMaterial` or into the timeline widgets**, and this holds for the game's built-in
backgrounds too (`WBP_DetailsPanel.BackgroundsData` is empty at runtime, which starves the last hop; the 4 track
headers stay at `BackgroundDynamicMaterial = null`; the subslot content stays on its design-time default). Because
the receiving widgets are simply never fed, **static asset-side changes cannot fix this** — there is no data value
we can author that the chain will pick up.

*Inference (marked as such):* the `BackgroundsData` map in `WBP_DetailsPanel` looks like the intended intermediary
that is populated only on a code path that does not run in this build, or that fails silently before filling the
map. We cannot confirm which from outside the binary.

---

## 6. What we are doing meanwhile (runtime workaround)

Until a cleaner path exists, we patch the widgets at runtime after the Create editor is constructed:

* For each live `WBP_BackgroundPreview_C`, call the **native** `UImage::SetBrushFromMaterial(row's Preview MI)` on
  its `Image_Preview`. This is verified to work and is reversible.
* For the timeline, call the game's **own** `WBP_TimelineSubslot_C:SetBackgroundContent(S_BackgroundChange)` on the
  background subslot of the currently selected step (and `WBP_SubslotContent_C:SetBackgroundContent(Background,
  ThroughBlack)` where needed). We have verified that this call is accepted and that the step's cell thumbnail then
  shows the selected background.
* Note: calling the Blueprint `WBP_BackgroundPreview_C:SetImage` / `SetPlaceholder` from outside is a **no-op**
  (0 changed pixels), so the Blueprint-level setters are not usable for this.
* Side effect: pushing the MIC directly bypasses the widget's own `SetDynamicMaterial` sizing path, so framing is
  driven by the `MI_*` `SpriteX/SpriteY/Width/Height` values. We do **not** currently re-derive the widget's own
  `WidgetSize` scalars, so framing can differ slightly from how the built-in rows would be framed.
* The refresh is selection-driven: we watch the panel's `BackgroundChange` (and the editor's selected step object)
  and re-push only when the selection actually changed, so switching backgrounds updates the previews instead of
  leaving a stale image behind.

This works, but it means every user must run our injector each session, and it is inherently fragile against
Blueprint refactors. A Blueprint-side fix would be strictly better.

---

## 7. Questions

1. Is `WBP_BackgroundPreview.PreviewMaterial` supposed to be set by the details panel when a step or track is
   selected, or is the preview block intentionally placeholder-only until something external fills it?
2. Is there an **intended public path** a modder could trigger instead of poking widgets directly — for example an
   event or dispatcher on the timeline slot objects (something like an `OnBackgroundChange`) that performs the
   selected-background → preview/timeline propagation?
3. Is the empty `WBP_DetailsPanel.BackgroundsData` at runtime expected, or does it indicate that the populate path
   is failing (we observe `BackgroundNamesPreviews` filled with the same 166 rows, but `BackgroundsData` empty)?
4. Would a future build consider reading `Preview` directly from `DA_Backgrounds.BackgroundMap` when the preview
   block and timeline entries are constructed? That would make the append-only mod path work with no runtime
   injection at all.
