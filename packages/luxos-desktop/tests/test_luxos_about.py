#!/usr/bin/env python3
"""LuxOS - O tomto pocitaci: pamet jako na krabici a texty z hardwaru bezpecne v Pango markup.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_about.py -v
"""
import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ABOUT = os.path.normpath(os.path.join(HERE, "..", "files", "bin", "luxos-about"))


def source():
    with open(ABOUT) as f:
        return f.read()


class About(unittest.TestCase):
    def mem(self, kb):
        prog = re.search(r"mem=\$\(awk '([^']+)' /proc/meminfo\)", source()).group(1)
        return subprocess.run(["awk", prog], input=f"MemTotal:       {kb} kB\n", capture_output=True,
                              text=True, check=True).stdout

    def test_memory_as_installed(self):
        # 16GB notebook s integrovanou grafikou: MemTotal 14,95 GiB - drive "15.0 GB"
        self.assertEqual(self.mem(15681220), "16 GB")
        self.assertEqual(self.mem(7500000), "8 GB")
        self.assertEqual(self.mem(32500000), "32 GB")
        self.assertEqual(self.mem(11800000), "12 GB")
        self.assertEqual(self.mem(1900000), "2 GB")       # mala VM
        self.assertEqual(self.mem(16777216), "16 GB")     # presne 16 GiB

    def test_short_gpu_names(self):
        # Dlouhe nazvy z lspci roztahly okno pres pul obrazovky
        fn = re.search(r"^gpu_names\(\) \{.*?^\}$", source(), re.M | re.S).group(0)
        lines = ["NVIDIA Corporation TU117M [GeForce GTX 1650 Mobile / Max-Q] (rev a1)",
                 "Advanced Micro Devices, Inc. [AMD/ATI] Lucienne (rev c1)",
                 "Intel Corporation Alder Lake-P GT2 [Iris Xe Graphics] (rev 0c)",
                 "Red Hat, Inc. Virtio 1.0 GPU (rev 01)"]
        out = subprocess.run(["bash", "-c", fn + "\ngpu_names"], input="\n".join(lines) + "\n",
                             capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertEqual(out, ["NVIDIA GeForce GTX 1650 Mobile / Max-Q", "AMD Lucienne", "Intel Iris Xe Graphics",
                               "Red Hat, Inc. Virtio 1.0 GPU"])

    def test_markup_escaped(self):
        fn = re.search(r"^esc\(\) \{.*\}$", source(), re.M).group(0)
        out = subprocess.run(["bash", "-c", fn + '\nesc "AT&T <Inc> \'x\'"'], capture_output=True, text=True,
                             check=True).stdout
        self.assertEqual(out, "AT&amp;T &lt;Inc&gt; 'x'")
        self.assertRegex(source(), r'vendor=\$\(esc "\$vendor"\) model=\$\(esc "\$model"\) cpu=\$\(esc "\$cpu"\) '
                                   r'gpu=\$\(esc "\$gpu"\)')


if __name__ == "__main__":
    unittest.main()
