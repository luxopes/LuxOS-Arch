# Testovaci program pro tests/test_luxos_tokens.py: vysledky pomocnych funkci luxos_tokens.lsl jako JSON
load json
load luxos_tokens as tokens

lut = []
for v in range(256):
    lut.append(tokens.srgb_linear(v))
end
# hystereze: kontrast klesa pres 2,0 a zase stoupa pres 2,3
ink = []
current = False
for c in [3.0, 2.4, 2.1, 1.99, 1.5, 2.0, 2.2, 2.29, 2.3, 2.5, 2.1, 1.9]:
    current = tokens.want_dark_ink(c, current)
    ink.append(current)
end
scrim = []
for lum in [0.0, 0.2, 0.4, 0.45, 0.5, 0.6, 0.7, 0.75, 0.8, 1.0]:
    scrim.append(tokens.scrim_strength(lum))
end
profile = []
ease = []
bezier = []
for i in range(11):
    t = Float(i) / 10.0
    profile.append(tokens.scrim_profile(t))
    ease.append(tokens.ease_in_out_cubic(t))
    bezier.append(tokens.cubic_bezier(tokens.CURVES["ease"], t))
end
print json.encode({"lut": lut, "ink": ink, "scrim": scrim, "profile": profile, "ease": ease, "bezier": bezier,
                   "white_contrast": [tokens.white_contrast(0.0), tokens.white_contrast(1.0), tokens.white_contrast(0.2)],
                   "contrast": tokens.contrast(tokens.luminance(255, 255, 255), tokens.luminance(29, 29, 43)),
                   "css": [tokens.css_color([61, 123, 255, 1.0]), tokens.css_color([0, 0, 0, 0.1]), tokens.hex8([0, 0, 0, 0.35]),
                           tokens.hex8([255, 255, 255, 1.0])],
                   "rgb01": tokens.rgb01([255, 0, 51, 0.5])})
