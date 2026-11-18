# Znělky budíku Hodin LuxOS

Obsah vygenerovaný umělou inteligencí (AI-generated content): StepFun, model
`stepaudio-3-music-preview` (API `/v1/audio/music`, úloha `text_to_music`, `instrumental=true`),
vygenerováno 2026-11-17 (Křišťál znovu 2026-11-18: první verze zněla jako Vánek). StepFun požaduje při šíření označení obsahu jako generovaného AI;
totéž je v metadatech souborů (komentář `AI-generated (StepFun stepaudio-3-music-preview)`).

Úprava z vygenerované skladby (1–2,5 min): začátek od prvního zvuku nad −45 dB, výřez dané délky,
náběh 30 ms, doznění 1,6 s, hlasitost EBU R128 −16 LUFS (špička −1,5 dBTP), Vorbis q4 48 kHz:

    ffmpeg -ss ZACATEK -t DELKA -i vstup.mp3 -af "afade=t=in:d=0.03,afade=t=out:st=DELKA-1.6:d=1.6,loudnorm=I=-16:TP=-1.5:LRA=11" \
        -ar 48000 -map_metadata -1 -c:a libvorbis -q:a 4 vystup.oga

| Soubor | Název v Hodinách | Délka | Zadání (caption) |
|---|---|---|---|
| `sunrise.oga` | Východ slunce | 18 s | Gentle uplifting morning wake-up melody, solo marimba and soft glockenspiel, bright major key, 110 bpm, clear repeating 4-bar motif, no drums, no vocals, clean studio sound, alarm clock ringtone |
| `chimes.oga` | Zvonkohra | 15 s | Cheerful wake-up ringtone, tubular bells and celesta playing a sparkling pentatonic melody, major key, 100 bpm, bright and clear, no drums, no vocals, clean studio sound |
| `crystal.oga` | Křišťál | 14 s | Sparkling music box and glass celesta, playful bouncing staccato melody in E major, fast 140 bpm, very high register, bright and cheerful, crisp plucked notes, no pads, no drums, no vocals, clean studio sound, alarm ringtone |
| `breeze.oga` | Vánek | 18 s | Calm gradual wake-up music, soft felt piano and warm ambient pads with light acoustic guitar, slow 72 bpm, peaceful major key, no drums, no vocals, relaxing alarm |
| `pulse.oga` | Puls | 12 s | Upbeat modern electronic alarm ringtone, bright plucky synth arpeggio and soft electronic beat, energetic 124 bpm, major key, catchy repeating hook, no vocals, clean mix |

Klasická znělka je systémový zvuk freedesktop `alarm-clock-elapsed.oga` (balík sound-theme-freedesktop).
