# orteki

orteki (West Flemish *ort ekier*, "listen") is an offline dictation and text-transformation tool: speech or existing text goes in, is shaped by a recipe, and the result lands where the user is typing.

## Language

### Using orteki

**Dictation**:
Using orteki by speaking: a recording is transcribed, run through a recipe, and the result is pasted.
_Avoid_: Voice input, recording (as a verb for the whole flow)

**Rewrite**:
Using orteki on existing text: the selected text (or the whole field) is run through a recipe and replaced by the result.
_Avoid_: Transform, transformation, edit

### Recipes

**Recipe**:
A named, ordered list of steps that transforms text, together with its language, vocabulary additions and recipe tests.
_Avoid_: Pipeline, workflow, preset, template

**Step**:
One transformation within a recipe; its output is the next step's input.
_Avoid_: Stage, action, node

**Active recipe**:
The recipe used for dictation and rewrite when no recipe-specific shortcut was pressed; it stays selected until changed.
_Avoid_: Default recipe, current recipe, selected recipe

**Recipe test**:
An input plus rule assertions about the output, stored inside a recipe, that checks the recipe behaves as intended.
_Avoid_: Test case, fixture, example

**Recipe variable**:
A named value a recipe can insert into its steps: the text, the focused app, the clipboard, or the date.
_Avoid_: Context variable, placeholder, parameter

### Vocabulary

**Vocabulary**:
The user's list of terms that speech recognition should get right; there is one global vocabulary, and each recipe can add to it.
_Avoid_: Dictionary, glossary, word list

**Term**:
One word or name in a vocabulary, with optional misheard spellings that should be corrected to it.
_Avoid_: Hint, correction, entry

**Misheard spelling**:
A wrong transcription of a term (e.g. "or taki" for "orteki") that recipes can correct.
_Avoid_: Alias, typo, variant

### Models

**Fit**:
How well a model runs on the current hardware: on the GPU, CPU only, or too large. Judged with whatever other models are loaded at the same time.
_Avoid_: Compatibility, suitability

**Catalogue**:
The built-in list of known models that orteki can recommend and download.
_Avoid_: Registry, store, library

### History

**Recording**:
One piece of captured audio from a dictation, with when and where it was made.
_Avoid_: Clip, audio, take

**Transcript**:
The text a speech model produced from a recording; a recording can have several, one per transcription.
_Avoid_: Transcription (for the text itself), raw text

**Run**:
One execution of a recipe on an input (a transcript or rewritten text), producing an output and a run log; an input can have several runs.
_Avoid_: Execution, job, result

**Run log**:
The per-step record of a run: each step's input, output, duration and any error.
_Avoid_: Trace, debug log

**Pin**:
A mark on a recording that keeps its audio regardless of retention settings.
_Avoid_: Star, favourite, bookmark, lock

### Desktop

**Indicator**:
The small always-on-top display that shows what orteki is doing right now.
_Avoid_: Overlay, HUD, popup, widget

**Excluded app**:
An application in which orteki never selects all text on its own.
_Avoid_: Blacklist, ignored app
