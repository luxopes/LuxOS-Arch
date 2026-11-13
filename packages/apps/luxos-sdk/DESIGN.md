# LuxOS application design

## Visual language

Use clear content hierarchy: a short window title, one main task, quiet supporting
text and a single emphasized action per section. The SDK palette uses ink text,
cool white surfaces, blue accents and generous spacing. Color communicates state;
also use text or an icon so meaning never depends on color alone.

Use 8 px as a spacing unit, approximately 32 px for outer workspace margins,
12-16 px between related controls and 20 px inside cards. Rounded corners should
support the structure of the application rather than turn every label into a pill.
Keep body text at the user's system font size. Use smaller labels sparingly.

## Icons and assets

Create original artwork. A layer-based design can use gradients, translucency,
highlights and shadows, but its silhouette must remain clear at 16, 24, 32 and
48 px. Review the actual exported image on both light and dark backgrounds.
Keep important content away from the edge and preserve transparency outside the
chosen shape. Use symbolic icons for small controls where a full-color icon would
be distracting. Store editable projects with the source and export standard SVG
or PNG assets for installation. The desktop needs no additional rendering service.

## Interaction

Give controls descriptive names, tooltips when useful and visible keyboard focus.
Every editing action should have undo where practical. Mark modified documents and
confirm before discarding work. Use native file choosers and do not overwrite files
without confirmation. Surface compiler errors and export failures in readable text.
Preserve the current document when opening or saving another document fails.

Make layouts scroll or reflow on small screens. Do not shrink text below a readable
size to fit panels. Support high DPI, keyboard navigation and light/dark previews.
Do not make AI sign-in a prerequisite for building an application.

## Responsiveness and memory

Use native GTK controls and update only when something changes. Long builds and
child programs must not block the main GUI thread. Close owned child processes when
their task is cancelled, without affecting other applications. Bound imported
images, history and log buffers. Release replaced images and native callbacks.
Avoid background services for tools whose work happens only while their window is
open. Measure idle CPU and memory in an isolated test session.
