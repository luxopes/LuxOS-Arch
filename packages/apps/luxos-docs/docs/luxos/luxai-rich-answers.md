# LuxAI rich answers

Since LuxAI 2.0.2-4 the desktop app shows charts, quizzes, calculators, diagrams, formulas, tables,
maps, image galleries, timelines and checklists directly in the answer, like ChatGPT – but drawn by
LuxAI itself (GTK and cairo), never as web pages or scripts from the model.

The model writes ordinary Markdown with a code block marked with a block name, for example `chart`. LuxAI
reads the block, checks it and builds its own widget. A block LuxAI cannot read is shown as normal
code with a short note ("This block could not be shown: …"), so nothing gets lost. The full format
is in `/usr/share/doc/luxai/rich-blocks.md`.

## What you can ask for

| Block | What you see | Example question |
|---|---|---|
| `chart` | bar, horizontal bar, line, area, scatter, pie or donut chart; point at it (or use the arrow keys) to read the values | "Show the population of the five biggest Czech cities as a chart." |
| `quiz` | questions with answer buttons, hints, explanations and a score; **Try again** | "Make a short quiz about the solar system." |
| `form` | calculator with sliders, number fields, switches, choices and results that update at once; **Send to LuxAI** sends your values as the next message | "Make me a mortgage calculator." |
| `table` | table sorted by clicking a column header, **Copy CSV** and **CSV** export (also for ordinary Markdown tables) | "Compare these laptops in a table." |
| `mermaid` | flowchart, sequence diagram, state diagram, timeline or pie chart, drawn without the internet | "Draw the process as a flowchart." |
| `svg` | a small vector drawing, cleaned of anything unsafe | "Draw a simple logo with a circle." |
| `$$…$$` | typeset formulas with real fractions, roots, sums, integrals and matrices | "Explain the quadratic formula." |
| `map` | the places and an **Open in Maps** button; the map picture after **Show map** | "Show me the main sights of Prague on a map." |
| `gallery` | an image carousel – images load only after **Load images** | "Show photos of the Charles Bridge." |
| `timeline` | events on a vertical time line | "Give me a timeline of the space race." |
| `checklist` | tasks with check boxes and "2 of 5 done" | "Make a packing checklist for a ski trip." |

LuxAI tells the model about these blocks in its instructions (Chat and Agent mode, Flash and Lite),
but plain text stays the default – the model uses a block only when it clearly helps.

## Your answers are kept

Quiz answers and hints, checklist ticks, calculator values, table sorting and your permission to load
a map or images are saved with the answer in the conversation (`~/.local/share/luxai`). When you open
the conversation again later, everything is as you left it. Nothing of this is sent to the model; only
**Send to LuxAI** in a calculator sends a message, and only when you click it.

## Copying and saving

Every rich block has **Copy** (the block source). Charts, diagrams and SVG images also have **PNG**
(twice the screen resolution) and **SVG**; tables have **Copy CSV** and **CSV**. A right click on a
formula copies its LaTeX source. Saved CSV files are safe to open in a spreadsheet: cells starting
with `=`, `+` or `@` are written as text, not as formulas.

## Safety and privacy

- The model cannot run code. Calculator results come from a small formula evaluator that knows only
  numbers, the calculator's own fields and a few math functions (`min`, `max`, `round`, `sqrt` …).
- SVG drawings are rebuilt from an allow-list of shapes and attributes before drawing: scripts,
  styles, embedded pages, images, links to other files or the internet, event handlers and XML entity
  tricks are removed, and size and complexity are limited. LuxAI notes under the image when it removed
  something.
- Images of a gallery are downloaded only after you allow it, through the same protection as LuxAI web
  pages: only public internet addresses (never your local network), at most 6 MB, and only real
  PNG, JPEG, GIF or WebP images (checked by their content). They are cached in
  `~/.cache/luxai/rich-images`.
- Map pictures come from LuxOS Maps (`luxos-maps --render-preview`, OpenStreetMap tiles). Like
  galleries they follow **LuxAI › Settings › Agent permissions › Network access**: "Ask" (default)
  shows **Show map** / **Load images**, "Allow" loads them at once, "Never" never loads them.
- Big or broken blocks are limited (for example 5000 chart points, 2000 table rows, 120 diagram
  nodes) and shown as code instead of slowing LuxAI down.

## Speed

Blocks are drawn only when they are on the screen and only once the block is complete; while an
answer streams in, a finished block is not rebuilt for every new word. Rendering a typical rich
answer takes a fraction of a second and adds no work while LuxAI is idle.

## Limits

- Only the LuxAI desktop app renders rich blocks. LuxOS Companion on the phone and the lux-ai.cz web
  chat show them as code (the format is ready for them).
- Mermaid: flowchart, sequence, state, timeline and pie diagrams only (no gantt, class or ER diagrams).
- Inline formulas in a sentence (`$…$`) stay in the text line, without stacked fractions.
- The map picture shows the route and its start and end; the other places are listed under it.
